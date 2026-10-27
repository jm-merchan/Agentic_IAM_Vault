"""Run the actual Bash CLI against an isolated Vault double."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p=pathlib.Path(os.environ['BLOCK_TEST_STATE']); s=json.loads(p.read_text()); a=sys.argv[1:]
s['events'].append(a)
def save(): p.write_text(json.dumps(s))
if a[:2]==['policy','write']:
    s['policies'][a[2]]=sys.stdin.read(); save()
elif a[:2]==['policy','read']:
    save(); print(s['policies'][a[2]])
elif a[:2]==['policy','list']:
    save(); print(json.dumps(list(s['policies'])))
elif a[0]=='read':
    save(); print(json.dumps({'data':{'ceiling_policies':list(s['policies']),'policies':list(s['policies'])}}))
elif a[:2]==['lease','revoke']:
    save(); sys.exit(1 if s.get('fail_revoke') else 0)
elif a[:2]==['kv','put']:
    s['generation']=json.loads(sys.stdin.read())['generation']; save()
else: sys.exit('Unexpected Vault command')
'''


@pytest.fixture
def lab(tmp_path):
    root=tmp_path/'repo'; scripts=root/'scripts/demo'; scripts.mkdir(parents=True)
    for name in ('common.sh', 'env-file.sh', 'block.sh'):
        shutil.copy(ROOT/'scripts/demo'/name, scripts/name)
    helper=root/'chatbot/scripts'; helper.mkdir(parents=True)
    shutil.copy(ROOT/'chatbot/scripts/access-controls.sh', helper)
    shutil.copy(ROOT/'demo.sh', root)
    (root/'.env').write_text('VERIFY_TENANT=https://test.invalid\n')
    state=tmp_path/'state'; (state/'vault').mkdir(parents=True)
    (state/'vault/config.env').write_text('VAULT_ADDR=https://test.invalid\nVAULT_TOKEN=test-only\nVAULT_CACERT=/test\n')
    data=tmp_path/'vault.json'
    data.write_text(json.dumps({'policies':{'lumen-block-'+k:'# inactive' for k in ('xai','database-read','database-write','decrypt')},'events':[]}))
    bin=tmp_path/'bin'; bin.mkdir(); (bin/'vault').write_text(MOCK); (bin/'vault').chmod(0o700)
    return root, data, {**os.environ,'PATH':str(bin)+os.pathsep+os.environ['PATH'],
                        'LUMEN_STATE_DIR':str(state), 'DEMO_ENV_FILE':str(root/'.env'), 'BLOCK_TEST_STATE':str(data)}


def run(lab, *args):
    root, _, env=lab
    result=subprocess.run(['bash',str(root/'demo.sh'),*args],env=env,text=True,capture_output=True,timeout=15)
    return result


@pytest.mark.parametrize('target,paths', [
    ('xai',['xai/creds/lumen','secrets/data/chatbot/xai-access']),
    ('database-read',['database/creds/chatbot-readonly','database/creds/chatbot-readwrite','database/creds/chatbot-contract']),
    ('database-write',['database/creds/chatbot-readwrite','database/creds/chatbot-contract']),
    ('decrypt',['transit/decrypt/lumen-applications','transform/decode/lumen-dni','transform/decode/lumen-iban',
                 'transit/decrypt/lumen-contracts','secrets/data/lumen-contracts/*']),
])
def test_scoped_block_and_reversible_unblock(lab, target, paths):
    r=run(lab,'block',target); assert r.returncode==0,r.stderr
    state=json.loads(lab[1].read_text()); policy=state['policies']['lumen-block-'+target]
    assert all(f'path "{p}" {{ capabilities = ["deny"] }}' in policy for p in paths)
    revocations=[e[-1] for e in state['events'] if e[:2]==['lease','revoke']]
    assert revocations==[p+'/' for p in paths if p.startswith(('xai/creds/','database/creds/'))]
    assert run(lab,'unblock',target).returncode==0
    state=json.loads(lab[1].read_text())
    assert 'deny' not in state['policies']['lumen-block-'+target]
    assert all('path' not in v for v in state['policies'].values())
    if target=='xai': assert len(state['generation'])==32


def test_independent_blocks_and_existing_blocks_survive_provisioning(lab):
    assert run(lab,'block','database-read').returncode==0
    assert run(lab,'block','database-write').returncode==0
    assert run(lab,'unblock','database-write').returncode==0
    root, data, env=lab
    before=json.loads(data.read_text())['policies']
    result=subprocess.run(['bash','-c','source scripts/demo/common.sh; load_inputs; source chatbot/scripts/access-controls.sh; initialize_block_policies'],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(data.read_text())['policies']==before
    assert 'deny' in before['lumen-block-database-read']


def test_revocation_failure_leaves_deny_active_and_reports_failure(lab):
    data=json.loads(lab[1].read_text()); data['fail_revoke']=True; lab[1].write_text(json.dumps(data))
    result=run(lab,'block','xai')
    assert result.returncode!=0 and 'deny permanece activo' in result.stderr
    assert 'deny' in json.loads(lab[1].read_text())['policies']['lumen-block-xai']


def test_invalid_target_never_calls_vault(lab):
    assert run(lab,'block','../anything').returncode!=0
    assert json.loads(lab[1].read_text())['events']==[]
