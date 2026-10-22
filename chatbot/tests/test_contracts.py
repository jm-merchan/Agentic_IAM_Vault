import asyncio,base64,hashlib,time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from app.contracts import ContractRequest,Contracts
from app.contracts_http import contract_download_router
from app.security import AccessDenied,Session
from app.trace_flow import build_flow


def setup():
    subject='writer';entity=str(uuid4())
    config={'contracts':{'enabled':True,'validator_subject':'validator','validator_username':'validator',
        'client_id':'ciba-client','validator_login_hint':{'username':'validator','realm':'cloudIdentityRealm'},
        'writers':[{'subject':subject,'entity_id':entity}]}}
    services=SimpleNamespace(config=config,role=lambda s:'readwrite' if 'writers' in s.groups else 'readonly',
        event=lambda *args:None,vault_post=AsyncMock(),vault_get=AsyncMock(),database=AsyncMock(),exchange=AsyncMock(return_value='obo'))
    manager=Contracts(services)
    session=Session('sid',subject=subject,groups=['writers'],expires_at=time.time()+600,task_agent='write')
    item=ContractRequest(str(uuid4()),str(uuid4()),subject,'write',time.time(),time.time()+500,
        {'snapshot_hash':'hash'},'Lumen contrato test',auth_req_id='auth-request')
    manager.requests[item.id]=item
    return manager,session,item

@pytest.mark.asyncio
@pytest.mark.parametrize('error,status',[('authorization_pending','waiting'),('slow_down','waiting'),('access_denied','denied'),('expired_token','expired'),('invalid_grant','error')])
async def test_no_write_without_successful_confirmation(error,status):
    manager,session,item=setup()
    manager._verify_request=AsyncMock(return_value=(400,{'error':error}))
    manager.formalize=AsyncMock()
    assert (await manager.poll(session,item.id))['status']==status
    manager.formalize.assert_not_called();manager.services.vault_post.assert_not_called()
    if error=='slow_down':assert item.interval==10
    if status=='waiting':
        await manager.poll(session,item.id)
        assert manager._verify_request.await_count==1
    else:assert not item.auth_req_id and not item.snapshot

@pytest.mark.asyncio
@pytest.mark.parametrize('wrong',['subject','self','audience','request','stale','hash','access_subject'])
async def test_confirmation_cannot_be_swapped(wrong):
    manager,session,item=setup()
    claims={'sub':'validator','iat':time.time(),'azp':'ciba-client'};access=dict(claims)
    if wrong=='subject':claims['sub']='other'
    if wrong=='self':claims['sub']=access['sub']=session.subject
    if wrong=='audience':claims['azp']='other'
    if wrong=='request':claims['urn:openid:params:jwt:claim:auth_req_id']='other'
    if wrong=='stale':claims['iat']=item.created_at-300
    if wrong=='hash':claims['at_hash']='bad'
    if wrong=='access_subject':access['sub']='other'
    manager.services.identity=SimpleNamespace(validate=lambda token,aud:claims if token=='id' else access)
    manager._verify_request=AsyncMock(return_value=(200,{'id_token':'id','access_token':'access'}))
    manager.formalize=AsyncMock()
    with pytest.raises(AccessDenied):await manager.poll(session,item.id)
    manager.formalize.assert_not_called()
    assert item.status=='error'

@pytest.mark.asyncio
async def test_success_is_only_reported_after_formalization_and_duplicates_do_not_write():
    manager,session,item=setup()
    audiences=[]
    def validate(token,audience):
        audiences.append(audience);return {'sub':'validator','iat':time.time()}
    manager.services.identity=SimpleNamespace(validate=validate)
    manager._verify_request=AsyncMock(return_value=(200,{'id_token':'id','access_token':'access'}))
    async def commit(*args):
        assert item.status=='waiting'
        item.contract_id=item.id
    manager.formalize=AsyncMock(side_effect=commit)
    results=await asyncio.gather(manager.poll(session,item.id),manager.poll(session,item.id))
    assert all(r['status']=='ready' for r in results)
    assert audiences==['ciba-client','ciba-client']
    manager.formalize.assert_awaited_once_with(session,item,'id')
    assert not item.snapshot and not item.auth_req_id

@pytest.mark.asyncio
async def test_vault_or_mysql_failure_never_reports_success():
    manager,session,item=setup()
    manager._verify_request=AsyncMock(return_value=(200,{'id_token':'id','access_token':'access'}))
    manager.services.identity=SimpleNamespace(validate=lambda *a:{'sub':'validator','iat':time.time()})
    manager.formalize=AsyncMock(side_effect=AccessDenied('SQL denied'))
    with pytest.raises(AccessDenied):await manager.poll(session,item.id)
    assert item.status=='error' and not item.auth_req_id

@pytest.mark.asyncio
@pytest.mark.parametrize('role,mode',[('reader','write'),('writer','read'),('writer','reveal')])
async def test_only_writer_with_creation_agent_can_request_contract(role,mode):
    manager,session,item=setup();session.groups=[role+'s'];session.task_agent=mode
    manager._verify_request=AsyncMock()
    with pytest.raises(AccessDenied):await manager.start(session,item.application_id)
    manager._verify_request.assert_not_called()

@pytest.mark.asyncio
async def test_draft_owner_enforced_before_ciba():
    manager,session,item=setup();manager.requests={}
    manager.services.database.return_value=[];manager._verify_request=AsyncMock()
    with pytest.raises(AccessDenied):await manager.start(session,item.application_id)
    assert manager.services.database.call_args.args[2]==(item.application_id,session.subject)
    manager._verify_request.assert_not_called()

@pytest.mark.asyncio
async def test_same_pending_draft_does_not_send_two_notifications():
    manager,session,item=setup();manager._verify_request=AsyncMock()
    assert (await manager.start(session,item.application_id))['id']==item.id
    manager._verify_request.assert_not_called()

@pytest.mark.asyncio
async def test_expiration_while_waiting_for_lock_is_checked():
    manager,session,item=setup();await item.lock.acquire()
    task=asyncio.create_task(manager.poll(session,item.id));await asyncio.sleep(0)
    item.expires_at=time.time()-1;item.lock.release()
    assert (await task)['status']=='expired' and not item.snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize('elapsed', [1, 601])
async def test_cleanup_does_not_clear_or_forget_an_inflight_confirmation(elapsed):
    manager,session,item=setup()
    manager._verify_request=AsyncMock(return_value=(200,{'id_token':'id','access_token':'access'}))
    manager.services.identity=SimpleNamespace(validate=lambda *a:{'sub':'validator','iat':time.time()})
    async def commit(*args):
        # Simulate the periodic cleanup firing while a slow SQL commit is awaited.
        item.expires_at=time.time()-elapsed
        manager.purge()
        assert manager.requests[item.id] is item
        assert item.status=='waiting' and item.snapshot['snapshot_hash']=='hash'
        item.contract_id=item.id
    manager.formalize=AsyncMock(side_effect=commit)
    assert (await manager.poll(session,item.id))['status']=='ready'
    assert not item.snapshot and not item.auth_req_id
    item.expires_at=time.time()-601
    manager.purge()
    assert item.id not in manager.requests


@pytest.mark.asyncio
async def test_cancelled_confirmation_is_terminal_and_clears_sensitive_state():
    manager,session,item=setup()
    manager._verify_request=AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await manager.poll(session,item.id)
    assert item.status=='error' and not item.snapshot and not item.auth_req_id
    assert not item.lock.locked()


@pytest.mark.asyncio
async def test_cancelled_ciba_start_does_not_leave_an_unusable_pending_request():
    manager,session,item=setup();manager.requests.clear()
    manager.services.database.return_value=[item.snapshot]
    manager._verify_request=AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await manager.start(session,item.application_id)
    saved=next(iter(manager.requests.values()))
    assert saved.status=='error' and not saved.snapshot and not saved.auth_req_id
    assert not manager.start_lock.locked()


@pytest.mark.asyncio
async def test_queued_pdf_download_rechecks_the_current_session():
    manager,session,item=setup();manager.download=AsyncMock(return_value=b'%PDF')
    identity=SimpleNamespace(sessions={'sid':session})
    lock=asyncio.Lock();await lock.acquire()
    app=FastAPI();app.include_router(contract_download_router(identity,manager,'lumen_session',{'sid':lock}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={'lumen_session':'sid'}) as client:
        task=asyncio.create_task(client.post(f'/api/contracts/{item.id}/pdf',headers={'Origin':'http://test','X-Lumen-PDF':'1'}))
        await asyncio.sleep(0)
        identity.sessions.pop('sid')
        lock.release()
        response=await task
    assert response.status_code==403
    manager.download.assert_not_called()


@pytest.mark.asyncio
async def test_pdf_is_not_returned_if_login_expires_during_download():
    manager,session,item=setup()
    async def expire(*args):
        session.expires_at=time.time()-1
        return b'%PDF-private'
    manager.download=AsyncMock(side_effect=expire)
    app=FastAPI();app.include_router(contract_download_router(SimpleNamespace(sessions={'sid':session}),manager,'lumen_session',{}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={'lumen_session':'sid'}) as client:
        response=await client.post(f'/api/contracts/{item.id}/pdf',headers={'Origin':'http://test','X-Lumen-PDF':'1'})
    assert response.status_code==403 and b'%PDF-private' not in response.content

@pytest.mark.asyncio
@pytest.mark.parametrize('wrong',['absent','status','hash','contract_id'])
async def test_download_requires_committed_owned_contract_and_matching_pdf(wrong):
    manager,session,item=setup();cid=str(uuid4());pdf=b'%PDF-test';digest=hashlib.sha256(pdf).hexdigest()
    manager.services.database.return_value=[] if wrong=='absent' else [{'status':'draft' if wrong=='status' else 'contratada','pdf_sha256':digest}]
    manager.services.vault_get.return_value={'data':{'data':{'contract_id':'other' if wrong=='contract_id' else cid,'pdf':base64.b64encode(pdf+(b'bad' if wrong=='hash' else b'')).decode()}}}
    with pytest.raises(AccessDenied):await manager.download(session,cid)
    assert manager.services.database.call_args.args[2]==(cid,session.subject)
    if wrong in ('absent','status'):manager.services.vault_get.assert_not_called()

@pytest.mark.asyncio
async def test_pdf_download_uses_owner_path_and_existing_obo():
    manager,session,item=setup();cid=str(uuid4());pdf=b'%PDF-test'
    manager.services.database.return_value=[{'status':'contratada','pdf_sha256':hashlib.sha256(pdf).hexdigest()}]
    manager.services.vault_get.return_value={'data':{'data':{'contract_id':cid,'pdf':base64.b64encode(pdf).decode()}}}
    assert await manager.download(session,cid)==pdf
    manager.services.exchange.assert_awaited_once_with(session,f'secrets/data/lumen-contracts/{manager.owner(session)}/{cid}',['read'])

@pytest.mark.asyncio
@pytest.mark.parametrize('invalid',['cookie','origin','header','id','method'])
async def test_http_download_requires_session_same_origin_and_post(invalid):
    manager,session,item=setup();manager.download=AsyncMock(return_value=b'%PDF')
    app=FastAPI();app.include_router(contract_download_router(SimpleNamespace(sessions={'sid':session}),manager,'lumen_session',{}))
    headers={'Origin':'http://test','X-Lumen-PDF':'1'};cookies={'lumen_session':'sid'}
    if invalid=='cookie':cookies={}
    if invalid=='origin':headers['Origin']='https://other'
    if invalid=='header':headers.pop('X-Lumen-PDF')
    cid='invalid' if invalid=='id' else item.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies=cookies) as client:
        r=await client.request('GET' if invalid=='method' else 'POST',f'/api/contracts/{cid}/pdf',headers=headers)
    assert r.status_code in (403,405)
    manager.download.assert_not_called()

@pytest.mark.asyncio
async def test_http_download_has_private_attachment_headers():
    manager,session,item=setup();manager.download=AsyncMock(return_value=b'%PDF')
    app=FastAPI();app.include_router(contract_download_router(SimpleNamespace(sessions={'sid':session}),manager,'lumen_session',{}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',cookies={'lumen_session':'sid'}) as client:
        r=await client.post(f'/api/contracts/{item.id}/pdf',headers={'Origin':'http://test','X-Lumen-PDF':'1'})
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert r.headers['content-type']=='application/pdf' and 'attachment;' in r.headers['content-disposition']


def test_ciba_is_not_misattributed_to_the_obo_agent():
    records=[{'span_id':'parent','parent_id':None,'name':'lumen.contract.confirm','start_ns':1,'end_ns':4,'duration_ms':3,'status':'UNSET','attributes':{'agent.identity':'chatbot-task-write'}},
             {'span_id':'ciba','parent_id':'parent','name':'verify.ciba_poll','start_ns':2,'end_ns':3,'duration_ms':1,'status':'UNSET','attributes':{'http.response.status_code':400,'auth.ciba.result':'authorization_pending'}}]
    flow=build_flow(records)
    assert flow['calls'][0]['agent_name']=='' and flow['calls'][0]['state']=='normal'


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_commit', [False, True])
async def test_formalization_publishes_only_after_commit_and_always_revokes(monkeypatch, fail_commit):
    import json
    manager, session, item = setup()
    item.snapshot.update(profile_ciphertext='vault:profile', dni_token='dni-token', iban_token='iban-token')
    item.approved_by = 'validator'
    pdf = b'%PDF-contract'
    monkeypatch.setattr('app.contracts.application_pdf', lambda *args: pdf)
    calls = []
    async def post(path, token, body):
        calls.append(path)
        if path == 'auth/ciba-contract/login':
            assert body == {'role':'validator', 'jwt':'confirmed-ciba-id-token'}
            return {'auth':{'client_token':'native-token'}}
        assert token == 'native-token'
        if path == 'transit/decrypt/lumen-applications':
            return {'data':{'plaintext':base64.b64encode(json.dumps({'full_name':'Fictional'}).encode()).decode()}}
        if path.startswith('transform/decode/'):
            return {'data':{'decoded_value':'fictional'}}
        if path == 'transit/encrypt/lumen-contracts':
            return {'data':{'ciphertext':'vault:encrypted-pdf'}}
        if path.startswith('secrets/data/'):
            assert calls.index('COMMIT') < calls.index(path)
            assert body['options'] == {'cas':0}
        return {}
    manager.services.vault_post.side_effect = post
    manager.services.vault_get.return_value = {'data':{'username':'temporary','password':'temporary'}}
    async def commit(*args):
        calls.append('COMMIT')
        if fail_commit:
            raise AccessDenied('SQL rejected')
        return {'contract_id':item.id, 'pdf_sha256':hashlib.sha256(pdf).hexdigest(),
                'owner_entity':manager.owner(session)}
    manager.commit = commit
    if fail_commit:
        with pytest.raises(AccessDenied):
            await manager.formalize(session,item,'confirmed-ciba-id-token')
        assert not any(path.startswith('secrets/data/') for path in calls)
    else:
        await manager.formalize(session,item,'confirmed-ciba-id-token')
        assert item.contract_id == item.id
    assert calls[-1] == 'auth/token/revoke-self'
    manager.services.exchange.assert_not_called()


@pytest.mark.parametrize('name,path', [('vault.write','auth/ciba-contract/login'),
    ('vault.read','database/creds/chatbot-contract'), ('mysql.query','')])
def test_native_ciba_steps_never_inherit_session_agent(name,path):
    records=[{'span_id':'parent','parent_id':None,'name':'lumen.contract.confirm','start_ns':1,'end_ns':4,
              'duration_ms':3,'status':'UNSET','attributes':{'agent.identity':'chatbot-task-write'}},
             {'span_id':'step','parent_id':'parent','name':name,'start_ns':2,'end_ns':3,'duration_ms':1,
              'status':'UNSET','attributes':{'auth.flow':'ciba_jwt','vault.path':path,'db.role':'contract'}}]
    call=build_flow(records)['calls'][0]
    assert call['agent_name']=='' and 'no utiliza OBO' in call['notes'][0]
    assert 'OBO' not in call['credential']
