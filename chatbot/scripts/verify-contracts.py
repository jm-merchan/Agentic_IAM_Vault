"""Real negative boundaries, CIBA, SQL commit/idempotency and owner OBO PDF read."""
import asyncio
from datetime import datetime,timezone
import hashlib,json,os,time
from pathlib import Path
from uuid import uuid4
import pymysql
from app.applications import generate_demo_form
from app.contract_oauth import same_permissions
from app.security import Identity,Session,load_config
from app.services import Services,VaultPermissionDenied,VaultResponseError
from app.telemetry import span,trace_id

async def main():
    config=load_config();config['contracts']['enabled']=True
    assert config['contracts'].get('auth_mode')=='oauth' and config['contracts'].get('version')==3
    identity=Identity(config);services=Services(config,identity);manager=services.contracts
    verify_request=manager._verify_request
    async def diagnosed_request(name,endpoint,data,credential=None):
        status,body=await verify_request(name,endpoint,data,credential)
        if endpoint=='/ciba' and status!=200:
            print('CIBA initiation rejected: '+json.dumps({k:body[k] for k in ('error','error_description') if k in body}),flush=True)
        return status,body
    manager._verify_request=diagnosed_request
    validate=manager._validate_confirmation
    async def diagnosed_confirmation(item,tokens):
        access=identity.validate(tokens['access_token'],config['contracts']['client_id'])
        projection={k:access.get(k) for k in ('sub','iat','exp','actor-token','authorization_details')}
        projection['jti_present']=bool(access.get('jti'))
        projection['request_created_at']=item.created_at
        projection['expected_rar']=item.authorization_details
        target=Path(os.environ['LUMEN_STATE_DIR'])/'contracts/oauth-migration/issued-claims.json'
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        target.write_text(json.dumps(projection,indent=2)+'\n');target.chmod(0o600)
        print('Signed CIBA claims: '+json.dumps({'actor':access.get('actor-token'),
              'rar_match':same_permissions(access.get('authorization_details'),item.authorization_details),
              'jti_present':bool(access.get('jti')),'iat':access.get('iat'),'exp':access.get('exp')}),flush=True)
        return await validate(item,tokens)
    manager._validate_confirmation=diagnosed_confirmation
    private=Path(os.environ['LUMEN_STATE_DIR'])
    tokens=json.loads((private/'manual/human-writer-task-write.json').read_text())
    claims=identity.validate(tokens['access_token'],config['task-write']['client_id'])
    session=Session('contract-live-test',subject=claims['sub'],groups=claims['groups'],access_token=tokens['access_token'],expires_at=claims['exp'],task_agent='write')
    checks=[]
    async def action(name,fn):
        with span(name,**{'user.id':session.subject,'agent.identity':'chatbot-task-write'}):
            session.traces.append(trace_id());return await fn()
    # No login/exchange with Vault is used: ordinary credentials cannot acquire
    # the contract role through the OAuth resource server.
    try:
        await action('lumen.contract.negative_login',lambda:services.vault_get('database/creds/chatbot-contract',tokens['id_token']))
        raise AssertionError('Ordinary ID token acquired contract credential')
    except VaultPermissionDenied:checks.append('ordinary ID token rejected by OAuth contract route')
    except VaultResponseError as exc:
        assert exc.status_code == 400
        checks.append('ordinary ID token rejected by OAuth contract route')
    code,_=await manager._verify_request('verify.ciba_credentials_check','/token',{'grant_type':'client_credentials'})
    assert code in (400,401,403);checks.append('CIBA client rejects client_credentials')
    token=await services.exchange(session,'database/creds/chatbot-contract',['read'])
    try:
        await services.vault_get('database/creds/chatbot-contract',token)
        raise AssertionError('Writer OBO acquired contract credential')
    except VaultPermissionDenied: checks.append('Writer OBO denied contract database credential')
    token=await services.exchange(session,'database/creds/chatbot-readwrite',['read'])
    credential=await services.vault_get('database/creds/chatbot-readwrite',token)
    def negative_sql(sql,params=(),expected=(1142,1143,1370)):
        with pymysql.connect(host='127.0.0.1',port=13306,user=credential['data']['username'],password=credential['data']['password'],database='scripting',autocommit=False) as c:
            try:
                with c.cursor() as cur:cur.execute(sql,params)
            except pymysql.MySQLError as exc:
                assert exc.args[0] in expected,exc.args[0]
                return
            finally:c.rollback()
            raise AssertionError('Writer SQL unexpectedly allowed: '+sql)
    negative_sql("UPDATE lumen_contracts.contracts SET status='contratada' WHERE application_id='not-present'")
    negative_sql('CALL lumen_contracts.formalize(%s,%s,%s,%s,%s,%s,%s,%s)',('x',)*8)
    negative_sql('SELECT pdf_ciphertext FROM lumen_contracts.contracts')
    checks.append('ordinary Writer SQL cannot formalize, call procedure or read protected PDF ciphertext')
    reference=str(uuid4())
    await action('lumen.application.save',lambda:services.save_application(session,generate_demo_form(),reference))
    result=await action('lumen.contract.request',lambda:manager.start(session,reference))
    assert not await services.database(session,'SELECT contract_id FROM lumen_contracts.contracts WHERE application_id=%s',(reference,))
    checks.append('no contract row while CIBA pending')
    print('CIBA request: '+result['binding_message'],flush=True)
    print('Negative checks passed; waiting for Validator to confirm this fictitious contract.',flush=True)
    commit=manager.commit
    async def twice(*args):
        first=await commit(*args);second=await commit(*args)
        assert first['contract_id']==second['contract_id'] and first['pdf_sha256']==second['pdf_sha256']
        checks.append('SQL retry is idempotent')
        return second
    manager.commit=twice
    formalize=manager.formalize
    approved={}
    async def direct_oauth(s,item,access_token):
        approved['token']=access_token
        get=services.vault_get
        async def observed_get(path,token):
            result=await get(path,token)
            if path=='database/creds/chatbot-contract' and token==access_token:
                approved['credential']=result
            return result
        services.vault_get=observed_get
        try:
            # The baseline ACL permits this namespace prefix, but the signed RAR
            # must confine the approval to the exact owner's contract path.
            other=f'secrets/data/lumen-contracts/{uuid4()}/{uuid4()}'
            try:
                await get(other,access_token)
                raise AssertionError('CIBA RAR accepted another PDF owner')
            except VaultPermissionDenied:checks.append('CIBA RAR denies a different PDF owner')
            try:
                await services.vault_post('auth/token/revoke',access_token,{'token':'hvs.nonexistent-test'})
                raise AssertionError('CIBA actor can revoke native Vault tokens')
            except VaultPermissionDenied:checks.append('revocation policy rejects native Vault token targets')
            await formalize(s,item,access_token)
        finally:
            services.vault_get=get
    manager.formalize=direct_oauth
    previous=None
    while time.time()<result['expires_at']:
        result=await action('lumen.contract.confirm',lambda:manager.poll(session,result['id']))
        if result['status']!=previous:print('Contract status: '+result['status'],flush=True);previous=result['status']
        if result['status']!='waiting':break
        await asyncio.sleep(5)
    if result['status']!='ready':raise RuntimeError('Contract not completed; inspect the CIBA trace. No contract was confirmed by this test.')
    try:
        await services.vault_get('database/creds/chatbot-contract',approved['token'])
        raise AssertionError('Completed CIBA OAuth JWT is still usable in Vault')
    except VaultPermissionDenied:checks.append('OAuth JWT is revoked in Vault after completion')
    c=approved['credential']['data']
    revoked=False
    for _ in range(20):
        try:
            connection=pymysql.connect(host='127.0.0.1',port=13306,user=c['username'],password=c['password'],connect_timeout=5)
            connection.close()
        except pymysql.MySQLError as exc:
            if exc.args[0] in (1045,3118):revoked=True;break
            raise
        await asyncio.sleep(.25)
    assert revoked,'Dynamic contract SQL user remains usable after JWT revocation'
    checks.append('SQL credential is revoked with the OAuth JWT')
    approved.clear()
    rows=await services.database(session,'SELECT contract_id,status FROM lumen_contracts.contracts WHERE application_id=%s',(reference,))
    assert len(rows)==1 and rows[0]['status']=='contratada'
    checks.append('one committed contract row with status contratada')
    document=await action('lumen.contract.download',lambda:manager.download(session,result['contract_id']))
    assert document.startswith(b'%PDF-') and hashlib.sha256(document).hexdigest()==result['digest']
    assert await manager.download(session,result['contract_id'])==document
    checks.append('owner downloads same committed PDF through OBO')
    # Obtain a fresh regular credential; the CIBA token has already been revoked.
    token=await services.exchange(session,'database/creds/chatbot-readwrite',['read'])
    credential=await services.vault_get('database/creds/chatbot-readwrite',token)
    negative_sql('UPDATE energy_applications SET plan_id=plan_id WHERE application_id=%s',(reference,),expected=(1644,))
    checks.append('contracted draft immutable to regular Writer SQL')
    # The PDF carries the synthetic DNI and IBAN in clear: keep it with the private state.
    output=Path(os.environ['LUMEN_STATE_DIR'])/'contracts/lumen-contrato-verificado.pdf'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(document)
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'flow':'contract-ciba-oauth','auth_mode':'oauth','passed':True,
        'client_id':config['contracts']['client_id'],'validator_subject':config['contracts']['validator_subject'],
        'actor_entity_id':config['contracts']['actor_entity_id'],
        'application_id':reference,'contract_id':result['contract_id'],'sha256':result['digest'],'checks':checks,'traces':session.traces}
    (Path(__file__).resolve().parents[1]/'docs/contracts-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Real CIBA OAuth, JWT/SQL revocation, SQL boundaries and PDF checks passed.',flush=True)

asyncio.run(main())
