"""Real negative boundaries, CIBA, SQL commit/idempotency and owner OBO PDF read."""
import asyncio
from datetime import datetime,timezone
import hashlib,json,os,time
from pathlib import Path
from uuid import uuid4
import pymysql
from app.applications import generate_demo_form
from app.security import AccessDenied,Identity,Session,load_config
from app.services import Services,VaultPermissionDenied,VaultResponseError
from app.telemetry import span,trace_id

async def main():
    config=load_config();config['contracts']['enabled']=True
    identity=Identity(config);services=Services(config,identity);manager=services.contracts
    private=Path(os.environ['LUMEN_STATE_DIR'])
    tokens=json.loads((private/'manual/human-writer-task-write.json').read_text())
    claims=identity.validate(tokens['access_token'],config['task-write']['client_id'])
    session=Session('contract-live-test',subject=claims['sub'],groups=claims['groups'],access_token=tokens['access_token'],expires_at=claims['exp'],task_agent='write')
    checks=[]
    async def action(name,fn):
        with span(name,**{'user.id':session.subject,'agent.identity':'chatbot-task-write'}):
            session.traces.append(trace_id());return await fn()
    # Neither the normal user token nor the client secret can replace CIBA.
    try:
        await action('lumen.contract.negative_login',lambda:services.vault_post('auth/ciba-contract/login','',{'role':'validator','jwt':tokens['id_token']}))
        raise AssertionError('Ordinary login accepted by CIBA role')
    except (VaultResponseError,VaultPermissionDenied):checks.append('ordinary login rejected by CIBA Vault role')
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
    previous=None
    while time.time()<result['expires_at']:
        result=await action('lumen.contract.confirm',lambda:manager.poll(session,result['id']))
        if result['status']!=previous:print('Contract status: '+result['status'],flush=True);previous=result['status']
        if result['status']!='waiting':break
        await asyncio.sleep(5)
    if result['status']!='ready':raise RuntimeError('Contract not completed; runtime remains disabled.')
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
    output=Path(__file__).resolve().parents[2]/'output/pdf/lumen-contrato-verificado.pdf'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(document)
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'flow':'contract-ciba','passed':True,
        'client_id':config['contracts']['client_id'],'validator_subject':config['contracts']['validator_subject'],
        'application_id':reference,'contract_id':result['contract_id'],'sha256':result['digest'],'checks':checks,'traces':session.traces}
    (Path(__file__).resolve().parents[1]/'docs/contracts-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Real CIBA contract, SQL boundaries and PDF checks passed.',flush=True)

asyncio.run(main())
