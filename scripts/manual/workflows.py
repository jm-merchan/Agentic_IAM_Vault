"""Run the real application services using tokens from the scripted OIDC flow.
Provisioning and policy changes remain Bash/Vault CLI. No mocks, ROPC or browser.
"""
import asyncio, copy, json, os, subprocess, time, uuid
from pathlib import Path
from datetime import datetime, UTC
import httpx
from app.security import load_config, Identity, Session, AccessDenied
from app.services import Services, VaultPermissionDenied
from app.applications import generate_demo_form, validate_form
from app.agent import reply, make_model
from app.model_config import select_provider
from app.guardrails import OUT_OF_SCOPE
from app.telemetry import span, trace_id, records_for, PROVIDER

ROOT=Path(os.environ['LUMEN_ROOT'])
PRIVATE=Path(os.environ['MANUAL'])
REPORT=Path(os.environ['MANUAL_RUN'])/'workflows.json'
checks=[]; traces=[]; active=set()
def check(name, passed):
    checks.append({'check':name,'passed':bool(passed)})
    print(f'{name}: {bool(passed)}',flush=True)
    if not passed: raise AssertionError(name)
async def action(name, call):
    with span('manual.'+name):
        tid=trace_id(); traces.append({'name':name,'trace_id':tid})
        return await call()
async def denied(name, call, exact=VaultPermissionDenied):
    try: await call()
    except exact: check(name,True)
    else: check(name,False)
def control(kind, enabled):
    subprocess.run(['bash',str(ROOT/'scripts/manual/control.sh'),kind,'on' if enabled else 'off'],check=True,stdout=subprocess.DEVNULL)
    if enabled: active.add(kind)
    else: active.discard(kind)
async def main():
    config=load_config(); identity=Identity(config); services=Services(config,identity)
    sessions={}
    for role in ('reader','writer','supervisor'):
        tokens=json.loads((PRIVATE/f'human-{role}.json').read_text())
        access=identity.validate(tokens['access_token'],config['oidc']['client_id'])
        id_claims=identity.validate(tokens['id_token'],config['oidc']['client_id'])
        check(role+' oidc identity and nonce', access['sub']==id_claims['sub'] and id_claims['nonce']==(PRIVATE/f'login-{role}/nonce').read_text())
        check(role+' may_act',access['may_act']['client_id']==config['oidc']['client_id'])
        s=Session(uuid.uuid4().hex,subject=access['sub'],name=role,groups=access['groups'],access_token=tokens['access_token'],expires_at=min(access['exp'],id_claims['exp']))
        sessions[role]=s
        result=await action(role+'.permissions',lambda s=s:services.permission_probe(s))
        (PRIVATE/f'permissions-{role}.txt').write_text(result)
        check(role+' nine Vault permissions','9 de 9 comprobaciones' in result)
        check(role+' catalog',len(await action(role+'.catalog',lambda s=s:services.plans(s)))==3)
    reader,writer,supervisor=(sessions[x] for x in ('reader','writer','supervisor'))
    check('all three provider profiles loaded',set(config['models'])=={'openai','xai','anthropic'})
    shared_before=copy.deepcopy(config)
    # Use the same runtime service and select xAI on a separate test session.
    # Do not replace the shared model config or load a side-channel credential.
    xai=services
    xai_session=copy.deepcopy(reader)
    select_provider(config,xai_session,'xai')
    first,_=await action('xai.initial',lambda:xai.model_credentials(xai_session))
    first_id=xai._xai_credential.api_key_id
    second,_=await action('xai.cache',lambda:xai.model_credentials(xai_session))
    check('xai reauthorized cache',first['api_key']==second['api_key'])
    first.pop('api_key');second.pop('api_key')
    form=generate_demo_form()
    for step in range(5):validate_form(form,step)
    check('five form steps validated',True)
    application_id=str(uuid.uuid4())
    await action('writer.application.save',lambda:services.save_application(writer,form,application_id))
    check('writer idempotent save',await action('writer.application.retry',lambda:services.save_application(writer,form,application_id))==application_id)
    for role,s in sessions.items():
        rows=await action(role+'.masked',lambda s=s:services.applications(s))
        row=next(r for r in rows if r['application_id']==application_id)
        check(role+' masked fields', form['dni'] not in str(row) and form['iban'] not in str(row) and 'profile_ciphertext' not in row)
        if role!='writer': await action(role+'.save.denied',lambda s=s,role=role:denied(role+' save denied',lambda:services.save_application(s,form,str(uuid.uuid4())),AccessDenied))
        if role!='supervisor':await action(role+'.reveal.denied',lambda s=s,role=role:denied(role+' reveal Vault 403',lambda:services.reveal_application(s,application_id)))
    revealed=await action('supervisor.reveal',lambda:services.reveal_application(supervisor,application_id))
    check('supervisor exact decrypt and decode',all(revealed[k]==form[k] for k in ('dni','iban','full_name','street')))
    # Old/fresh JWT comparisons use the same actual RAR and policies as the application.
    async def blocked_paths(kind,session,paths):
        old={}
        fixture=config['runtime']['permission_probe']
        for path in paths:
            cap=['update'] if kind=='decrypt' else ['read']
            payload=None
            if path.startswith('transit/'):payload={'ciphertext':fixture['profile_ciphertext']}
            elif path.startswith('transform/'):
                field=path.rsplit('-',1)[1];payload={'value':fixture[field]['token'],'transformation':'lumen-'+field}
            old[path]=(await services.exchange(session,path,cap),payload,cap)
        async def request(path,token,payload):
            return await services.vault_post(path,token,payload) if payload else await services.vault_get(path,token)
        control(kind,True)
        try:
            for path,(token,payload,cap) in old.items():
                await action(kind+'.old',lambda path=path,token=token,payload=payload:denied(kind+' old '+path,lambda:request(path,token,payload)))
                fresh=await services.exchange(session,path,cap)
                await action(kind+'.fresh',lambda path=path,fresh=fresh,payload=payload:denied(kind+' fresh '+path,lambda:request(path,fresh,payload)))
            if kind=='database-write':check('write block preserves SELECT',len(await services.plans(writer))==3)
            if kind=='decrypt':await denied('decrypt block stops reveal',lambda:services.reveal_application(supervisor,application_id))
        finally:control(kind,False)
        for path,(token,payload,_) in old.items():
            await action(kind+'.restored',lambda path=path,token=token,payload=payload:request(path,token,payload))
            check(kind+' same JWT restored '+path,True)
    await blocked_paths('database-write',writer,['database/creds/chatbot-readwrite'])
    await blocked_paths('database-read',writer,['database/creds/chatbot-readonly','database/creds/chatbot-readwrite'])
    await blocked_paths('decrypt',supervisor,['transit/decrypt/lumen-applications','transform/decode/lumen-dni','transform/decode/lumen-iban'])
    for provider in ('openai','xai','anthropic'):
        previous_messages=copy.deepcopy(reader.messages)
        other_selection=writer.model_provider
        select_provider(config,reader,provider)
        check(provider+' selection preserves history',reader.messages==previous_messages)
        check(provider+' selection isolated from writer',writer.model_provider==other_selection)
        result=await action(provider+'.agent.catalog',lambda:reply(services,reader,'Consulta con tu herramienta los tres planes del catálogo de esta demo y compara sus precios.'))
        tid=traces[-1]['trace_id']; rec=records_for({tid}); names={r['name'] for r in rec}
        check(provider+' grounded catalog via OBO',{'lumen.catalogue.response','mysql.query','verify.obo_exchange'} <= names and bool(result))
        model_span=provider+'.chat'
        model_records=[r for r in rec if r['name']==model_span]
        check(provider+' model trace matches selection',bool(model_records) and all(
            r['attributes'].get('gen_ai.request.model')==config['models'][provider]['model'] for r in model_records))
        if provider in ('openai','anthropic'):
            minted=next(r['attributes'] for r in rec if r['name']=='spiffe.mint_jwt_svid')
            svid=json.loads(minted['spiffe.jwt_svid']);decoded=json.loads(minted['spiffe.jwt_svid.decoded'])
            check(provider+' SVID trace signature and subject',decoded['signature_verified'] and decoded['claims']['sub']==config['models'][provider]['spiffe_id'])
            check(provider+' SVID absent from prompts',all(svid not in json.dumps(r['attributes']) for r in model_records))
        result=await action(provider+'.agent.tavily',lambda:reply(services,reader,'Busca en la web información sobre autoconsumo solar y cita las fuentes.'))
        names={r['name'] for r in records_for({traces[-1]['trace_id']})}
        check(provider+' scope allows energy search',result!=OUT_OF_SCOPE)
        check(provider+' Deep Agents Tavily tool', 'tool.buscar_en_web' in names)
        check(provider+' Tavily cited sources','https://' in result)
        blocked=await action(provider+'.guardrail.weather',lambda:reply(services,reader,'¿Qué tiempo hace hoy en Palencia?'))
        check(provider+' weather rejected',blocked==OUT_OF_SCOPE)
        reader.messages.extend([{'role':'user','content':'¿Qué tiempo hace hoy en Palencia?'},{'role':'assistant','content':blocked}])
        reader.messages[:]=reader.messages[-20:]
        follow=await action(provider+'.guardrail.followup',lambda:reply(services,reader,'venga'))
        names={r['name'] for r in records_for({traces[-1]['trace_id']})}
        check(provider+' followup rejected without Vault or model',follow==OUT_OF_SCOPE and not any(n.startswith(('vault.','openai.','anthropic.','xai.')) for n in names))
    check('shared provider configuration unchanged',config==shared_before)
    if xai:
        while xai._xai_credential.expires_at-time.monotonic()>209:
            print('Waiting for actual xAI credential refresh threshold',flush=True)
            await asyncio.sleep(min(10,xai._xai_credential.expires_at-time.monotonic()-209))
        replacement,_=await action('xai.refresh',lambda:xai.model_credentials(xai_session))
        check('xai replaced before expiry',xai._xai_credential.api_key_id!=first_id)
        answer=await action('xai.inference',lambda:make_model(replacement).ainvoke('Responde solo: XAI OK'))
        check('xai dynamic inference','XAI OK' in str(answer.content))
        old_token=await xai.client_token('xai')
        control('xai',True)
        try:
            for path in ('xai/creds/lumen','secrets/data/chatbot/xai-access'):
                await action('xai.block.old',lambda path=path:denied('xai old '+path,lambda:xai.vault_get(path,old_token)))
            await action('xai.block.new',lambda:denied('xai cache reauthorization denied',lambda:xai.model_credentials(xai_session)))
            async with httpx.AsyncClient() as client:
                revoked=False
                for attempt in range(16):
                    response=await client.get('https://api.x.ai/v1/models',headers={'Authorization':'Bearer '+replacement['api_key']})
                    revoked=response.status_code in (401,403) or (response.status_code==400 and any(s in response.text.lower() for s in ('incorrect api key','invalid api key')))
                    if revoked:break
                    if response.status_code!=200:break
                    await asyncio.sleep(2)
                (PRIVATE/'xai-revocation.json').write_text(json.dumps({'status':response.status_code,'attempts':attempt+1,'revoked':revoked}))
            check('xai issued key revoked',revoked)
        finally:control('xai',False);replacement.pop('api_key',None)
        restored,_=await action('xai.restored',lambda:xai.model_credentials(xai_session));restored.pop('api_key')
        check('xai available after unblock',True)
        subprocess.run(['bash',str(ROOT/'scripts/manual/control.sh'),'cleanup-xai'],check=True,stdout=subprocess.DEVNULL)
    PROVIDER.force_flush()
    # Trace export and audit ingestion may lag a few seconds; retry read-only queries.
    async with httpx.AsyncClient(timeout=20) as client:
        for item in traces:
            tid=item['trace_id']; rec=records_for({tid})
            vault_spans=[r for r in rec if r['name'] in ('vault.read','vault.write')]
            def correlated(events):
                for record in vault_spans:
                    parent='00-'+tid+'-'+record['span_id']+'-01'
                    matching=[e for e in events if parent in e.get('request',{}).get('headers',{}).get('traceparent',[]) and e.get('request',{}).get('path')==record['attributes']['vault.path']]
                    if not {'request','response'} <= {e.get('type') for e in matching}:return False
                return True
            for attempt in range(20):
                t=await client.get('http://127.0.0.1:3200/api/traces/'+tid)
                a=await client.get('http://127.0.0.1:3100/loki/api/v1/query_range',params={'query':'{service="vault-audit",audit_mode="raw"} |= "'+tid+'"','since':'1h','limit':500})
                events=[json.loads(v[1]) for s in a.json()['data']['result'] for v in s['values']]
                if t.status_code==200 and correlated(events):break
                await asyncio.sleep(2)
            check('trace and audit '+item['name'],t.status_code==200 and correlated(events))
            item.update(vault_requests=len(vault_spans),raw_audit_events=len(events))
    return application_id
async def run():
    report={'checked_at':datetime.now(UTC).isoformat(),'method':'scripted OIDC Authorization Code + PKCE; real application services; no browser','checks':checks,'traces':traces}
    try:
        report['application_id']=await main();report['all_passed']=True
    except Exception as exc:
        report['all_passed']=False;report['error_type']=type(exc).__name__
        raise
    finally:
        for kind in list(active):control(kind,False)
        PROVIDER.force_flush()
        REPORT.parent.mkdir(parents=True,exist_ok=True)
        REPORT.write_text(json.dumps(report,indent=2)+'\n')
if __name__ == '__main__':
    asyncio.run(run())
