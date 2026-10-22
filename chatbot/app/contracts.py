"""Drafts use OBO; only a CIBA-bound Vault login can obtain SQL contract credentials."""
from __future__ import annotations
import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import secrets
import time
from uuid import UUID, uuid4

import httpx
import pymysql
from . import lab_capture
from .application_pdf import application_pdf
from .http_capture import request_hook
from .rar import LAB_CONTEXT
from .security import AccessDenied, ISSUER
from .task_agents import task_allows
from .telemetry import span, trace_id

TERMINAL = {'denied', 'expired', 'error', 'ready'}
SNAPSHOT_SQL = '''SELECT a.*,p.name AS plan_name,p.price_kwh,
 SHA2(CAST(JSON_ARRAY(a.application_id,a.subject_id,a.plan_id,a.profile_ciphertext,a.dni_token,a.iban_token,p.name,p.price_kwh) AS CHAR),256) AS snapshot_hash
 FROM energy_applications a JOIN energy_plans p ON p.id=a.plan_id
 WHERE a.application_id=%s AND a.subject_id=%s'''
PUBLIC_COLUMNS = 'application_id,contract_id,requestor_subject,owner_entity,validator_subject,status,confirmed_at,plan_name,price_kwh,snapshot_hash,pdf_sha256'

@dataclass
class ContractRequest:
    id: str
    application_id: str
    subject: str
    mode: str
    created_at: float
    expires_at: float
    snapshot: dict = field(repr=False)
    binding_message: str
    language: str = 'es'
    auth_req_id: str = field(default='', repr=False)
    interval: float = 5
    next_poll: float = 0
    status: str = 'waiting'
    contract_id: str = ''
    digest: str = ''
    approved_by: str = ''
    traces: list[str] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def clear(self):
        self.snapshot = {}
        self.auth_req_id = ''

    def public(self):
        return {name:getattr(self,name) for name in ('id','application_id','created_at','expires_at',
            'binding_message','status','contract_id','digest','approved_by','traces')}

class Contracts:
    def __init__(self, services):
        self.services = services
        self.requests: dict[str, ContractRequest] = {}
        self.start_lock = asyncio.Lock()

    @property
    def config(self):
        return self.services.config.get('contracts', {})

    def writer(self, session):
        session.require_login()
        return self.services.role(session) == 'readwrite'

    def eligible(self, session):
        return bool(self.config.get('enabled') and self.writer(session) and task_allows(session, 'write')
                    and session.subject != self.config.get('validator_subject'))

    def owner(self, session):
        owners = [u for u in self.config.get('writers',[]) if u['subject'] == session.subject]
        if len(owners) != 1:
            raise AccessDenied('Tu identidad Writer no está configurada para contratar.')
        return owners[0]['entity_id']

    def purge(self):
        now = time.time()
        for item in self.requests.values():
            if now >= item.expires_at and item.status not in TERMINAL:
                item.status = 'expired'
                item.clear()
        self.requests = {k:v for k,v in self.requests.items() if now < v.expires_at + 600}

    def owned(self, session, request_id):
        session.require_login()
        self.purge()
        item = self.requests.get(request_id)
        if not item or item.subject != session.subject or item.mode != session.task_agent:
            raise AccessDenied('Esta contratación no pertenece a tu identidad y agente actuales.')
        return item

    def list_for(self, session):
        session.require_login()
        self.purge()
        return [r.public() for r in reversed(list(self.requests.values()))
                if r.subject == session.subject and r.mode == session.task_agent]
    async def _verify_request(self, name, endpoint, data, credential=None):
        credential = credential or self.config
        with span(name, **{'auth.flow': 'ciba', 'oauth.client.name': 'vault-chatbot-contract'}) as current:
            lab_capture.request(current, 'POST', ISSUER + endpoint, data,
                                basic_auth=(credential['client_id'], credential['client_secret']))
            async with httpx.AsyncClient(event_hooks={'request': [request_hook]}, timeout=30) as client:
                response = await client.post(ISSUER + endpoint, data=data,
                    auth=(credential['client_id'], credential['client_secret']))
            current.set_attribute('http.response.status_code', response.status_code)
            lab_capture.response(current, response)
            try:
                body = response.json()
            except ValueError:
                raise AccessDenied('Verify no ha devuelto una respuesta CIBA válida.') from None
            if not isinstance(body, dict):
                raise AccessDenied('Verify no ha devuelto una respuesta CIBA válida.')
            if response.status_code != 200:
                current.set_attribute('auth.ciba.result', str(body.get('error', 'unknown'))[:80])
            return response.status_code, body

    async def _validate_confirmation(self, item, tokens):
        identity = self.services.identity
        cid = self.config['client_id']
        id_claims = await asyncio.to_thread(identity.validate, tokens['id_token'], cid)
        access = await asyncio.to_thread(identity.validate, tokens['access_token'], cid)
        if id_claims['sub'] != self.config['validator_subject'] or access['sub'] != id_claims['sub'] \
                or access['sub'] == item.subject:
            raise AccessDenied('La aprobación no corresponde al Validador dedicado.')
        if 'azp' in id_claims and id_claims['azp'] != cid:
            raise AccessDenied('La aprobación no corresponde al cliente CIBA.')
        if id_claims['iat'] < item.created_at - 60:
            raise AccessDenied('La respuesta CIBA no corresponde a esta petición.')
        # In poll mode auth_req_id is bound by the authenticated token request. Check
        # these optional ID token claims too when the provider includes them.
        if id_claims.get('urn:openid:params:jwt:claim:auth_req_id', item.auth_req_id) != item.auth_req_id:
            raise AccessDenied('La respuesta CIBA no corresponde a esta petición.')
        if 'at_hash' in id_claims:
            expected = base64.urlsafe_b64encode(hashlib.sha256(tokens['access_token'].encode()).digest()[:16]).rstrip(b'=').decode()
            if not secrets.compare_digest(expected, id_claims['at_hash']):
                raise AccessDenied('La respuesta CIBA no corresponde a esta petición.')
        return id_claims['sub']

    async def start(self, session, reference, language='es'):
        session.require_login()
        if not self.eligible(session):
            raise AccessDenied('Contratar requiere Writer, un agente de creación y CIBA configurado.')
        UUID(reference)
        self.owner(session)
        async with self.start_lock:
            self.purge()
            for item in self.requests.values():
                if item.subject == session.subject and item.application_id == reference and item.status == 'waiting':
                    if item.mode != session.task_agent:
                        raise AccessDenied('Hay una contratación pendiente con otro agente. Espera a que caduque.')
                    return item.public()
            if len(self.requests) >= 100 or sum(r.subject == session.subject and r.status == 'waiting' for r in self.requests.values()) >= 3:
                raise AccessDenied('Ya hay contrataciones pendientes. Complétalas o espera a que caduquen.')
            rows = await self.services.database(session, SNAPSHOT_SQL, (reference, session.subject))
            if len(rows) != 1:
                raise AccessDenied('Solo puedes contratar tus propios borradores.')
            rid, now = str(uuid4()), time.time()
            item = ContractRequest(rid, reference, session.subject, session.task_agent, now, now+600,
                rows[0], 'Lumen contrato ' + reference[:8] + ' ' + rid[:6], language)
            self.requests[rid] = item
            context = LAB_CONTEXT.set({**LAB_CONTEXT.get(), **self.metadata(item)})
            try:
                status, body = await self._verify_request('verify.ciba_start', '/ciba', {
                    'scope':'openid profile', 'login_hint':json.dumps(self.config['validator_login_hint']),
                    'binding_message':item.binding_message, 'requested_expiry':600})
                if status != 200 or not isinstance(body.get('auth_req_id'),str) or not body['auth_req_id'] \
                        or not isinstance(body.get('expires_in'),(int,float)) or not 0 < body['expires_in'] <= 86400:
                    raise AccessDenied('Verify no ha iniciado CIBA. El borrador sigue sin contratar.')
                item.auth_req_id = body['auth_req_id']
                item.expires_at = min(item.expires_at,time.time()+body['expires_in'])
                item.interval = max(5,min(60,float(body.get('interval',5))))
                item.next_poll = time.time()+item.interval
                item.traces.append(trace_id())
                self.services.event(session,'Contratación solicitada',item.binding_message)
                return item.public()
            except Exception:
                item.status='error'; item.clear()
                raise
            finally:
                LAB_CONTEXT.reset(context)

    def metadata(self, item):
        return {'approval.id':item.id, 'approval.application':item.application_id,
            'approval.requestor':item.subject, 'approval.validator':self.config['validator_subject'],
            'approval.sha256':item.digest, 'approval.operation':'contract'}

    async def poll(self, session, request_id):
        item = self.owned(session,request_id)
        async with item.lock:
            self.owned(session,request_id)
            if item.status != 'waiting' or time.time() < item.next_poll:
                return item.public()
            if not self.eligible(session):
                raise AccessDenied('Tu sesión no permite contratar.')
            item.next_poll=time.time()+item.interval
            context=LAB_CONTEXT.set({**LAB_CONTEXT.get(), **self.metadata(item)})
            try:
                status,body=await self._verify_request('verify.ciba_poll','/token',{
                    'grant_type':'urn:openid:params:grant-type:ciba','auth_req_id':item.auth_req_id})
                if status != 200:
                    error=body.get('error')
                    if error in ('authorization_pending','slow_down'):
                        if error=='slow_down': item.interval+=5
                        item.next_poll=time.time()+item.interval
                        return item.public()
                    item.status='denied' if error=='access_denied' else 'expired' if error=='expired_token' else 'error'
                    item.clear()
                    return item.public()
                with span('lumen.contract.validate_validator'):
                    item.approved_by=await self._validate_confirmation(item,body)
                session.require_login()
                if time.time() >= item.expires_at:
                    item.status='expired';item.clear()
                else:
                    await self.formalize(session,item,body['id_token'])
                    item.status='ready';item.clear()
                self.services.event(session,'Contratación',item.application_id+' · '+item.status)
                return item.public()
            except Exception:
                item.status='error';item.clear()
                raise
            finally:
                item.traces.append(trace_id());item.traces[:]=item.traces[-20:]
                LAB_CONTEXT.reset(context)

    async def formalize(self, session, item, ciba_jwt):
        # This login is verified again by Vault: issuer, signature, audience and
        # validator subject. Ordinary OBO tokens do not receive this policy.
        context=LAB_CONTEXT.set({**LAB_CONTEXT.get(),'auth.flow':'ciba_jwt','agent.identity':''})
        token=''
        try:
            auth=await self.services.vault_post('auth/ciba-contract/login','',{'role':'validator','jwt':ciba_jwt})
            token=auth['auth']['client_token']
            credential=await self.services.vault_get('database/creds/chatbot-contract',token)
            profile=(await self.services.vault_post('transit/decrypt/lumen-applications',token,
                {'ciphertext':item.snapshot['profile_ciphertext']}))['data']['plaintext']
            profile=json.loads(base64.b64decode(profile,validate=True))
            for field in ('dni','iban'):
                profile[field]=(await self.services.vault_post('transform/decode/lumen-'+field,token,
                    {'value':item.snapshot[field+'_token'],'transformation':'lumen-'+field}))['data']['decoded_value']
            document=await asyncio.to_thread(application_pdf,{**item.snapshot,'status':'contratada'},
                profile,item.id,item.language,datetime.now(timezone.utc))
            if len(document) > 2_000_000:
                raise AccessDenied('El contrato PDF supera el tamaño admitido.')
            digest=hashlib.sha256(document).hexdigest()
            LAB_CONTEXT.set({**LAB_CONTEXT.get(),'approval.sha256':digest})
            encrypted=(await self.services.vault_post('transit/encrypt/lumen-contracts',token,
                {'plaintext':base64.b64encode(document).decode()}))['data']['ciphertext']
            session.require_login()
            if time.time() >= item.expires_at:
                raise AccessDenied('La confirmación ha caducado antes de formalizar.')
            record=await self.commit(credential,item,self.owner(session),digest,encrypted)
            # A concurrent retry returns the original committed PDF, never a new contract.
            if record['pdf_sha256'] != digest:
                clear=(await self.services.vault_post('transit/decrypt/lumen-contracts',token,
                    {'ciphertext':record['pdf_ciphertext']}))['data']['plaintext']
                document=base64.b64decode(clear,validate=True)
            if hashlib.sha256(document).hexdigest() != record['pdf_sha256']:
                raise AccessDenied('El PDF no coincide con el contrato registrado.')
            item.contract_id=record['contract_id'];item.digest=record['pdf_sha256']
            LAB_CONTEXT.set({**LAB_CONTEXT.get(),'approval.sha256':item.digest})
            path=f'secrets/data/lumen-contracts/{record["owner_entity"]}/{record["contract_id"]}'
            from .services import VaultResponseError
            try:
                await self.services.vault_post(path,token,{'options':{'cas':0},'data':{
                    'pdf':base64.b64encode(document).decode(),'sha256':item.digest,
                    'application_id':item.application_id,'contract_id':item.contract_id}})
            except VaultResponseError as exc:
                if exc.status_code != 400: raise
                existing=(await self.services.vault_get(path,token))['data']['data']
                if existing.get('sha256') != item.digest:
                    raise AccessDenied('El PDF almacenado no coincide con el contrato.') from None
        finally:
            if token:
                try:
                    await self.services.vault_post('auth/token/revoke-self',token,{})
                except Exception:
                    # Both the token and its dynamic SQL credential have short hard TTLs.
                    self.services.event(session,'Revocación pendiente','La credencial CIBA caduca en un máximo de 120 s','error')
            LAB_CONTEXT.reset(context)

    async def commit(self, credential, item, owner, digest, encrypted):
        sql='CALL lumen_contracts.formalize(%s,%s,%s,%s,%s,%s,%s,%s)'
        params=(item.application_id,item.id,item.subject,owner,item.approved_by,
                item.snapshot['snapshot_hash'],digest,encrypted)
        def execute():
            with pymysql.connect(host='127.0.0.1',port=13306,user=credential['data']['username'],
                password=credential['data']['password'],database='lumen_contracts',connect_timeout=10,
                read_timeout=30,write_timeout=30,cursorclass=pymysql.cursors.DictCursor,autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql,params)
                    row=cursor.fetchone()
                    while cursor.nextset(): pass
                    if not row or row['status'] != 'contratada':
                        raise AccessDenied('MySQL no ha confirmado la contratación.')
                    return row
        with span('mysql.query',**{'db.system.name':'mysql','db.namespace':'lumen_contracts',
            'db.operation.name':'CALL','db.role':'contract','contract.application':item.application_id}) as current:
            lab_capture.capture(current,'connection','Credencial dinámica utilizada en MySQL',{
                'host':'127.0.0.1','port':13306,'database':'lumen_contracts',**credential['data'],
                'lease_id':credential.get('lease_id'),'lease_duration':credential.get('lease_duration')})
            lab_capture.capture(current,'query','Consulta y parámetros enviados',{'statement':sql,'parameters':params})
            try:
                record=await asyncio.to_thread(execute)
            except pymysql.MySQLError as exc:
                current.set_attribute('db.error.code', int(exc.args[0]))
                raise AccessDenied('MySQL no ha formalizado el contrato. El borrador puede haber cambiado; actualiza la bandeja.') from None
            lab_capture.capture(current,'result','Resultado de MySQL',{k:str(v) for k,v in record.items() if k!='pdf_ciphertext'})
            return record

    async def download(self, session, contract_id):
        if not self.writer(session):
            raise AccessDenied('El contrato solo está disponible para el Writer que lo solicitó.')
        UUID(contract_id)
        rows=await self.services.database(session,'SELECT '+PUBLIC_COLUMNS+' FROM lumen_contracts.contracts WHERE contract_id=%s AND requestor_subject=%s',
            (contract_id,session.subject))
        if len(rows)!=1 or rows[0]['status']!='contratada':
            raise AccessDenied('El borrador todavía no está contratado o pertenece a otro usuario.')
        record=rows[0]
        path=f'secrets/data/lumen-contracts/{self.owner(session)}/{contract_id}'
        token=await self.services.exchange(session,path,['read'])
        from .services import VaultResponseError
        try:
            data=(await self.services.vault_get(path,token))['data']['data']
        except VaultResponseError as exc:
            if exc.status_code!=404: raise
            raise AccessDenied('Contrato formalizado; el PDF está pendiente de publicar. Solicita su recuperación con CIBA.') from None
        document=base64.b64decode(data['pdf'],validate=True)
        if data.get('contract_id')!=contract_id or hashlib.sha256(document).hexdigest()!=record['pdf_sha256']:
            raise AccessDenied('El PDF no coincide con el contrato registrado.')
        self.services.event(session,'Contrato descargado',contract_id)
        return document
