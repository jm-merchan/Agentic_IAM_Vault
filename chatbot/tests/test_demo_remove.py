"""Exercise the real Bash teardown against isolated CLI/API doubles.

No network, real kubectl, process supervisor or production state is accessed.
Only fixed /tmp paths in a private copy of the scripts are redirected to fixtures.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p=pathlib.Path(os.environ['REMOVE_TEST_STATE']); s=json.loads(p.read_text())
cmd=pathlib.Path(sys.argv[0]).name; a=sys.argv[1:]
with p.with_suffix('.events').open('a') as f: f.write(json.dumps([cmd,a])+'\n')
def save(): p.write_text(json.dumps(s))
def out(value): print(json.dumps(value))
if cmd=='lsof':
    if '-iTCP:8443' in a: print('424242'); sys.exit(0)
    sys.exit(1)
if cmd=='ps': print('kubectl --context workshop -n vault port-forward --address 127.0.0.1 pod/vault-0 8443:8200'); sys.exit(0)
if cmd=='launchctl': sys.exit(0)
if cmd=='plutil': sys.exit(1)
if cmd=='helm': sys.exit(0)
if cmd=='vault':
    if a[:2]==['secrets','list']: out({'xai/':{'type':'vault-plugin-secrets-xai'}})
    elif a[:2]==['namespace','lookup']:
        if s.get('namespace_error'):
            print('Error reading namespace: permission denied (403)',file=sys.stderr);sys.exit(2)
        if s.get('namespace_absent'):
            print('Namespace not found',file=sys.stderr);sys.exit(2)
        out({'data':{'id':'fixture'}})
    elif a[:2]==['lease','revoke']:
        if s.get('fail_revoke'): sys.exit(1)
    else: sys.exit('unexpected vault command')
elif cmd=='kubectl':
    if 'exec' in a: out({'initialized':True,'sealed':False})
    elif 'get' in a:
        i=a.index('get'); kind=a[i+1]; rest=a[i+2:]
        if kind=='namespaces': out({'items':[{'metadata':{'name':n}} for n in s['namespaces']]})
        elif kind=='namespace': print('\n'.join('namespace/'+n for n in rest if n in s['namespaces']))
        elif kind=='statefulset':
            if 'vault' in s['namespaces']: print('statefulset.apps/vault')
        elif kind=='pv':
            if rest and not rest[0].startswith('-'):
                if any(v['metadata']['name']==rest[0] for v in s['pvs']): print('persistentvolume/'+rest[0])
            else: out({'items':s['pvs']})
        else: sys.exit('unexpected kubectl get')
    elif 'delete' in a:
        i=a.index('delete'); assert a[i+1]=='namespace'
        names=[n for n in a[i+2:] if not n.startswith('-')]
        assert set(names)<=set(['vault','mysql','lumen-observability'])
        s['namespaces']=[n for n in s['namespaces'] if n not in names]
        if not s.get('pv_stuck'): s['pvs']=[v for v in s['pvs'] if v['spec']['claimRef']['namespace'] not in names]
        save()
    elif 'wait' in a: sys.exit(1 if s.get('pv_stuck') else 0)
    else: sys.exit('unexpected kubectl command')
elif cmd=='curl':
    method=a[a.index('--request')+1] if '--request' in a else 'GET'
    dest=pathlib.Path(a[a.index('--output')+1])
    url=next(v for v in a if v.startswith('https://'))
    path='/' + url.split('/',3)[3]; base=path.split('?')[0]
    code=200; body={}
    resources=s['resources']
    if base=='/oauth2/token': body={'access_token':'synthetic-access-token'}
    elif base=='/v1/sys/namespaces/verify': sys.exit('Vault must be accessed through CLI')
    elif method=='DELETE':
        assert base in resources
        assert resources[base]['fixture_lumen']
        if s.get('fail_delete'): code=403
        else:
            del resources[base]; save(); code=204
    elif base=='/v1.0/applications':
        apps=[{'name':r['name'],'_links':{'self':{'href':k}}} for k,r in resources.items() if k.startswith(base+'/')]
        body={'_embedded':{'applications':apps},'totalCount':len(apps)}
    elif base=='/v1.0/sts/oauth/clients':
        clients=[r for k,r in resources.items() if k.startswith(base+'/')]
        body={'clients':clients,'total':len(clients)}
    elif base in ('/v2.0/Users','/v2.0/Groups'):
        term=a[a.index('--data-urlencode')+1].split('"')[1]
        key='userName' if base.endswith('Users') else 'displayName'
        rows=[r for k,r in resources.items() if k.startswith(base+'/') and r[key]==term]
        body={'Resources':rows,'totalResults':len(rows)}
    elif base in resources: body=resources[base]
    else: code=404
    dest.write_text(json.dumps(body)); print(code,end='')
else: sys.exit('unexpected command: '+cmd)
'''


@pytest.fixture
def lab(tmp_path):
    root=tmp_path/'workspace'; scripts=root/'scripts/demo'; scripts.mkdir(parents=True)
    legacy=tmp_path/'legacy'; legacy.mkdir()
    telemetry=tmp_path/'telemetry'; telemetry.mkdir(); (telemetry/'spans.jsonl').write_text('fixture')
    for source in (ROOT/'scripts/demo').glob('*.sh'):
        content=source.read_text().replace('/tmp/vault/',str(legacy)+'/').replace('/tmp/lumen-telemetry',str(telemetry))
        (scripts/source.name).write_text(content)
    # Forward lifecycle is exercised separately in test_demo_forwards.py.
    # Teardown fixtures have a synthetic listener, never a real process to signal.
    with (scripts/'common.sh').open('a') as common:
        common.write('\nstart_forward() { :; }\n')
    shutil.copy(ROOT/'demo.sh',root/'demo.sh')
    state=tmp_path/'state'; (state/'vault').mkdir(parents=True)
    keys=json.dumps({'root_token':'synthetic-root','unseal_keys_b64':['synthetic-unseal']})
    (state/'vault/cluster-keys.json').write_text(keys); (legacy/'cluster-keys.json').write_text(keys)
    config=f'VAULT_TOKEN=synthetic-root\nVAULT_ADDR=https://127.0.0.1:8443\nVAULT_CACERT={state}/vault/vault.ca\n'
    (state/'vault/config.env').write_text(config); (legacy/'config.env').write_text(config)
    (state/'vault/vault.ca').write_text('fixture')
    for folder in ('mysql','runtime','vault-chatbot-storage'):
        (state/folder).mkdir(); (state/folder/'fixture').write_text('fixture')
    (state/'unrelated').mkdir(); (state/'unrelated/keep').write_text('keep')
    env_file=root/'.env'
    env_file.write_text('VERIFY_TENANT=https://fixture.verify.ibm.com\nVERIFY_ADMIN_CLIENT_ID=admin\nVERIFY_ADMIN_CLIENT_SECRET=synthetic\n')
    resources={}
    for i,name in enumerate(('vault-chatbot-oidc','vault-chatbot-research','vault-chatbot-xai','vault-authn-entry')):
        resources[f'/v1.0/applications/a{i}']={'name':name,'providers':{'oidc':{'properties':{'clientId':f'cid{i}'}}},'fixture_lumen':i<3}
    resources['/v1.0/sts/oauth/clients/sts']={'clientName':'vault-chatbot-sts','clientId':'sts','fixture_lumen':True}
    for i,role in enumerate(('reader','writer','supervisor')):
        username=f'lumen-{role}'
        resources[f'/v2.0/Users/u{i}']={'id':f'u{i}','userName':username,'emails':[{'value':username+'@example.invalid'}],'urn:ietf:params:scim:schemas:extension:ibm:2.0:User':{'realm':'cloudIdentityRealm'},'fixture_lumen':True}
        resources[f'/v2.0/Groups/g{i}']={'id':f'g{i}','displayName':f'chatbot-{role}s','members':[{'value':f'u{i}'}],'fixture_lumen':True}
    pvs=[{'metadata':{'name':'pvc-'+ns},'spec':{'claimRef':{'namespace':ns},'persistentVolumeReclaimPolicy':'Delete'}} for ns in ('vault','mysql','lumen-observability')]
    data=tmp_path/'remote.json'; data.write_text(json.dumps({'namespaces':['vault','mysql','lumen-observability','unrelated'],'pvs':pvs,'resources':resources}))
    bindir=tmp_path/'bin'; bindir.mkdir()
    for name in ('curl','kubectl','vault','helm','launchctl','plutil','lsof','ps'):
        file=bindir/name; file.write_text(MOCK); file.chmod(0o700)
    env={**os.environ,'PATH':str(bindir)+os.pathsep+os.environ['PATH'],'DEMO_ENV_FILE':str(env_file),'LUMEN_STATE_DIR':str(state),'REMOVE_TEST_STATE':str(data)}
    return {'root':root,'state':state,'data':data,'env':env,'legacy':legacy,'telemetry':telemetry,'env_file':env_file}


def run(lab,*args):
    return subprocess.run(['bash',str(lab['root']/'demo.sh'),'remove',*args],env=lab['env'],text=True,capture_output=True,timeout=45)


def events(lab):
    return [json.loads(line) for line in lab['data'].with_suffix('.events').read_text().splitlines()]


def change(lab,**values):
    data=json.loads(lab['data'].read_text()); data.update(values); lab['data'].write_text(json.dumps(data))


def is_delete(event):
    cmd,args=event
    return (cmd=='curl' and 'DELETE' in args) or (cmd=='kubectl' and 'delete' in args) or (cmd=='helm' and 'uninstall' in args)


def test_preview_preserves_resources_and_recovery(lab):
    before=lab['data'].read_text(); result=run(lab,'--dry-run')
    assert result.returncode==0,result.stderr+result.stdout
    assert lab['data'].read_text()==before
    assert not any(is_delete(e) or e[0]=='launchctl' for e in events(lab))
    assert (lab['state']/'vault/cluster-keys.json').exists()
    assert json.loads((lab['state']/'last-run.json').read_text())['dry_run'] is True


def test_contract_cleanup_preserves_real_validator_account(lab):
    remote=json.loads(lab['data'].read_text())
    remote['resources'].update({
        '/v2.0/Users/real-admin': {'id':'real-admin','userName':'operator@example.com',
            'fixture_lumen':False},
        '/v2.0/Groups/contract-validators': {'id':'contract-validators',
            'displayName':'chatbot-validators','externalId':'lumen-demo:contract-validators',
            'members':[{'value':'real-admin'}], 'fixture_lumen':True},
        '/v1.0/applications/contract-client': {'name':'vault-chatbot-contract',
            'providers':{'oidc':{'properties':{'clientId':'contract-client'}}},'fixture_lumen':True},
    })
    lab['data'].write_text(json.dumps(remote))
    result=run(lab)
    assert result.returncode==0,result.stderr+result.stdout
    resources=json.loads(lab['data'].read_text())['resources']
    assert '/v2.0/Users/real-admin' in resources
    assert '/v2.0/Groups/contract-validators' not in resources
    assert '/v1.0/applications/contract-client' not in resources


def test_remove_is_scoped_ordered_and_repeatable(lab):
    inputs=lab['env_file'].read_bytes(); result=run(lab)
    assert result.returncode==0,result.stderr+result.stdout
    remote=json.loads(lab['data'].read_text())
    assert list(remote['resources'])==['/v1.0/applications/a3']
    assert remote['namespaces']==['unrelated'] and not remote['pvs']
    assert lab['env_file'].read_bytes()==inputs
    assert (lab['state']/'unrelated/keep').exists()
    assert not (lab['state']/'vault').exists()
    assert not (lab['legacy']/'cluster-keys.json').exists()
    assert not (lab['telemetry']/'spans.jsonl').exists()
    log=events(lab)
    revoke=next(i for i,e in enumerate(log) if e[0]=='vault' and 'revoke' in e[1])
    assert revoke < next(i for i,e in enumerate(log) if is_delete(e))
    for cmd,args in log:
        if cmd=='curl':
            method=args[args.index('--request')+1]
            assert args[args.index('--retry')+1] == ('2' if method=='GET' else '0')
        if cmd=='curl' and 'DELETE' in args:
            url=next(a for a in args if a.startswith('https://'))
            if '/v2.0/' in url: assert url.endswith('?notifyType=NONE')
    result=run(lab)
    assert result.returncode==0,result.stderr+result.stdout


def test_namespace_lookup_error_is_not_treated_as_absence(lab):
    change(lab,namespace_error=True); result=run(lab)
    assert result.returncode!=0
    assert (lab['state']/'vault/cluster-keys.json').exists()
    assert not any(is_delete(e) for e in events(lab))


def test_interrupted_install_without_verify_can_be_removed(lab):
    change(lab,namespace_absent=True); result=run(lab)
    assert result.returncode==0,result.stderr+result.stdout
    assert not any(e[0]=='vault' and 'revoke' in e[1] for e in events(lab))


@pytest.mark.parametrize('failure',['fail_delete','fail_revoke','pv_stuck'])
def test_failure_preserves_recovery_keys(lab,failure):
    change(lab,**{failure:True}); result=run(lab)
    assert result.returncode!=0
    assert (lab['state']/'vault/cluster-keys.json').exists()
    assert (lab['legacy']/'cluster-keys.json').exists()
    log=events(lab)
    assert any(e[0]=='vault' and 'revoke' in e[1] for e in log)
    if failure=='fail_revoke': assert not any(is_delete(e) for e in log)
    if failure=='fail_delete':
        assert any(e[0]=='curl' and 'DELETE' in e[1] for e in log)
        assert not any(e[0]=='kubectl' and 'delete' in e[1] for e in log)
    if failure=='pv_stuck': assert any(e[0]=='kubectl' and 'wait' in e[1] for e in log)


def test_group_with_unrelated_member_aborts_before_changes(lab):
    data=json.loads(lab['data'].read_text()); data['resources']['/v2.0/Groups/g0']['members'].append({'value':'external-user'})
    change(lab,resources=data['resources']); result=run(lab)
    assert result.returncode!=0
    assert not any(is_delete(e) or e[0]=='launchctl' for e in events(lab))


def test_retained_volume_aborts_before_changes(lab):
    data=json.loads(lab['data'].read_text()); data['pvs'][0]['spec']['persistentVolumeReclaimPolicy']='Retain'
    change(lab,pvs=data['pvs']); result=run(lab)
    assert result.returncode!=0
    assert not any(is_delete(e) or e[0]=='launchctl' for e in events(lab))
