"""Session-owned OAuth pairs; only lab-issued JWTs can reach the revoker."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import math
import os
import time

import httpx
import pymysql
from opentelemetry.trace import Status, StatusCode

from .rar import authorization_details
from .security import AccessDenied, ISSUER
from .task_agents import actor_credential
from .telemetry import headers, span, trace_id
from .vault_clock import raise_for_clock_mismatch

PATHS = {'delegated': 'database/creds/chatbot-readonly',
         'direct': 'secrets/data/chatbot/xai-access'}


def payload_for(claims, now=None):
    now = time.time() if now is None else now
    expiry = claims.get('exp')
    if (claims.get('iss') != ISSUER or not isinstance(claims.get('jti'), str)
            or not claims['jti'] or type(expiry) not in (int, float)
            or not math.isfinite(expiry) or expiry <= now):
        raise AccessDenied('El token del laboratorio ha caducado. Crea una pareja nueva.')
    return {'issuer': claims['iss'], 'unique_id': claims['jti'], 'exp': math.ceil(expiry - now) + 15}


@dataclass
class Pair:
    sid: str
    subject: str
    mode: str
    task_agent: str
    tokens: list = field(default_factory=list, repr=False)
    claims: list = field(default_factory=list, repr=False)
    sql: dict = field(default_factory=dict, repr=False)
    lease_deadline: float = 0
    blocked: bool = False
    verified: bool = False
    rows: list = field(default_factory=list)
    traces: list = field(default_factory=list)
    sql_result: str = ''

    def public(self):
        def project(claims):
            result = {k: claims.get(k) for k in ('iss', 'jti', 'sub', 'exp')}
            if isinstance(claims.get('actor-token'), dict):
                result['actor-token'] = {'sub': claims['actor-token'].get('sub')}
            return result
        return dict(mode=self.mode, path=PATHS[self.mode], blocked=self.blocked, verified=self.verified,
                    tokens=[project(c) for c in self.claims], rows=list(self.rows), traces=list(self.traces),
                    sql_result=self.sql_result)


class OAuthRevocationLab:
    def __init__(self, services, token=None):
        self.services = services
        self._token = os.environ.pop('CHATBOT_OAUTH_REVOKER_TOKEN', '') if token is None else token
        self._pairs = {}
        self._lock = asyncio.Lock()
        self._maintenance = None

    @property
    def available(self):
        return bool(self._token)

    def start(self):
        if self.available:
            self._maintenance = asyncio.create_task(self._maintain())

    async def _maintain(self):
        ticks = 0
        while True:
            await asyncio.sleep(60)
            async with self._lock:
                for key, pair in list(self._pairs.items()):
                    session = self.services.identity.sessions.get(pair.sid)
                    if (not session or session.expires_at <= time.time()
                            or max((c['exp'] for c in pair.claims), default=0) <= time.time()):
                        with suppress(httpx.HTTPError, AccessDenied):
                            await self._clean(pair)
                            self._pairs.pop(key, None)
            ticks += 1
            if ticks % 20 == 0:
                with suppress(httpx.HTTPError):
                    async with self._client() as client:
                        await client.post('/v1/auth/token/renew-self', json={})

    async def close(self):
        if self._maintenance:
            self._maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await self._maintenance
        async with self._lock:
            for pair in self._pairs.values():
                with suppress(httpx.HTTPError, AccessDenied):
                    await self._clean(pair)
            self._pairs.clear()
        if self._token:
            with suppress(httpx.HTTPError):
                async with self._client() as client:
                    await client.post('/v1/auth/token/revoke-self')
            self._token = ''

    def _client(self):
        return httpx.AsyncClient(base_url=self.services.config['vault_addr'],
                                 verify=self.services.vault_tls, timeout=30,
                                 headers={'X-Vault-Token': self._token, 'X-Vault-Namespace': 'verify'})

    def _guard(self, session, mode):
        self.services.role(session)
        if mode not in PATHS:
            raise AccessDenied('El modo de laboratorio no es válido.')
        if not self.available:
            raise AccessDenied('Reinicia Lumen con el script actualizado para preparar el laboratorio.')

    def _owned(self, session, mode):
        self._guard(session, mode)
        pair = self._pairs.get((session.sid, mode))
        if not pair or pair.subject != session.subject or pair.task_agent != session.task_agent:
            raise AccessDenied('Crea primero los tokens de esta sesión y agente.')
        return pair

    def view(self, session, mode):
        self._guard(session, mode)
        pair = self._pairs.get((session.sid, mode))
        if pair and pair.subject == session.subject and pair.task_agent == session.task_agent:
            return pair.public()
        return None

    @staticmethod
    def _remember(pair):
        tid = trace_id()
        if tid and tid not in pair.traces:
            pair.traces.append(tid)

    async def _request(self, pair, label, token, *, revoke=None, phase=''):
        path = 'auth/token/revoke-oauth' if revoke is not None else PATHS[pair.mode]
        method = 'POST' if revoke is not None else 'GET'
        actor = ('oauth-revocation-operator' if revoke is not None else 'chatbot-xai'
                 if pair.mode == 'direct' else 'chatbot-' + actor_credential(self.services.config, pair.task_agent))
        # Deliberately capture metadata only: no operator bearer, SQL password or JWT body.
        with span('vault.write' if revoke is not None else 'vault.read', **{
            'vault.path': path, 'vault.namespace': 'verify', 'http.request.method': method,
            'agent.identity': actor, 'auth.flow': 'revocation_operator' if revoke else pair.mode,
            'revocation.lab.token': label, 'revocation.lab.phase': phase}) as current:
            index = 0 if label == 'A' else 1
            if len(pair.claims) > index:
                current.set_attribute('revocation.lab.seconds_until_exp', pair.claims[index]['exp'] - time.time())
                current.set_attribute('revocation.lab.unique_id', pair.claims[index]['jti'])
            async with self._client() as client:
                result = await client.request(method, '/v1/' + path, json=revoke,
                    headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify', **headers()})
            current.set_attribute('http.response.status_code', result.status_code)
            body = result.json() if result.content else {}
            current.set_attribute('vault.request_id', body.get('request_id', ''))
            pair.rows.append(dict(phase=phase, token=label, status=result.status_code, trace_id=trace_id()))
            pair.rows[:] = pair.rows[-20:]
            raise_for_clock_mismatch(result, token, current)
            return result.status_code, body

    async def _direct(self):
        credential = self.services.config.get('xai', {})
        if not credential.get('client_secret'):
            raise AccessDenied('El agente directo chatbot-xai no está configurado.')
        with span('verify.client_credentials', **{'agent.identity': 'chatbot-xai', 'auth.flow': 'client_credentials'}) as current:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(ISSUER + '/token',
                    auth=(credential['client_id'], credential['client_secret']),
                    data={'grant_type': 'client_credentials', 'scope': 'openid profile email',
                          'authorization_details': json.dumps(authorization_details(PATHS['direct'], ['read']))})
            current.set_attribute('http.response.status_code', response.status_code)
            if response.status_code != 200:
                raise AccessDenied('Verify no ha emitido el token directo del laboratorio.')
            return response.json()['access_token']

    async def _sql_accepts(self, credential):
        def connect():
            with span('mysql.query', **{'db.role': 'readonly', 'db.operation.name': 'SELECT',
                                       'db.statement': 'SELECT 1'}) as current:
                try:
                    with pymysql.connect(host='127.0.0.1', port=13306, connect_timeout=5,
                            user=credential['username'], password=credential['password']) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT 1')
                            return cursor.fetchone()[0] == 1
                except pymysql.MySQLError as exc:
                    if exc.args[0] not in (1045, 3118):
                        raise AccessDenied('No se pudo comprobar la conexión MySQL.') from None
                    current.set_attribute('db.error.code', exc.args[0])
                    current.set_status(Status(StatusCode.ERROR))
                    return False
        return await asyncio.to_thread(connect)

    async def prepare(self, session, mode):
        self._guard(session, mode)
        async with self._lock:
            key = (session.sid, mode)
            if old := self._pairs.get(key):
                await self._clean(old)
                self._pairs.pop(key, None)
            pair = Pair(session.sid, session.subject, mode, session.task_agent)
            self._pairs[key] = pair  # Retain partially prepared pairs for cleanup on failure.
            self._remember(pair)
            try:
                rar = authorization_details(PATHS[mode], ['read'])
                for _ in range(2):
                    token = (await self.services.exchange(session, PATHS[mode], ['read'])
                             if mode == 'delegated' else await self._direct())
                    claims = await asyncio.to_thread(self.services.identity.validate, token, None)
                    payload_for(claims)
                    expected_subject = session.subject if mode == 'delegated' else self.services.config['xai']['client_id']
                    actor = claims.get('actor-token')
                    expected_actor = self.services.config[actor_credential(self.services.config, session.task_agent)]['client_id']
                    if (claims['sub'] != expected_subject or claims.get('authorization_details') != rar
                            or (mode == 'delegated' and (not isinstance(actor, dict) or actor.get('sub') != expected_actor))
                            or (mode == 'direct' and actor)):
                        raise AccessDenied('El token no coincide con la identidad y el RAR solicitados.')
                    pair.tokens.append(token)
                    pair.claims.append(claims)
                if pair.claims[0]['jti'] == pair.claims[1]['jti']:
                    raise AccessDenied('Verify no ha emitido identificadores distintos para A y B.')
                for index, label in enumerate(('A', 'B')):
                    status, response = await self._request(pair, label, pair.tokens[index], phase='before')
                    if status != 200:
                        raise AccessDenied('El acceso inicial no devuelve HTTP 200. Revisa los permisos en la traza.')
                    if mode == 'delegated' and index == 0:
                        pair.sql = response['data']
                        pair.lease_deadline = time.monotonic() + response['lease_duration']
                        if not await self._sql_accepts(pair.sql):
                            raise AccessDenied('La credencial MySQL inicial no permite conectar.')
                return pair.public()
            except Exception:
                await self._clean(pair)
                self._pairs.pop(key, None)
                raise

    async def block(self, session, mode):
        async with self._lock:
            pair = self._owned(session, mode)
            self._remember(pair)
            if pair.blocked:
                return pair.public()
            if min(c['exp'] for c in pair.claims) - time.time() <= 30:
                raise AccessDenied('Quedan menos de 30 segundos. Crea otra pareja para distinguir bloqueo y caducidad.')
            status, _ = await self._request(pair, 'A', self._token,
                                            revoke=payload_for(pair.claims[0]), phase='revoke')
            if status not in (200, 204):
                raise AccessDenied('Vault no ha aceptado el bloqueo. Consulta el resultado real en la traza.')
            pair.blocked = True
            return pair.public()

    async def check(self, session, mode):
        async with self._lock:
            pair = self._owned(session, mode)
            self._remember(pair)
            if len(pair.tokens) != 2 or min(c['exp'] for c in pair.claims) - time.time() <= 30:
                raise AccessDenied('Quedan menos de 30 segundos. Crea otra pareja para distinguir bloqueo y caducidad.')
            statuses = []
            for index, label in enumerate(('A', 'B')):
                status, _ = await self._request(pair, label, pair.tokens[index], phase='after')
                statuses.append(status)
            pair.verified = bool(pair.blocked and statuses == [403, 200]
                                 and min(c['exp'] for c in pair.claims) - time.time() > 30)
            if pair.verified:
                # Local signature verification intentionally still succeeds after Vault's denylist.
                await asyncio.to_thread(self.services.identity.validate, pair.tokens[0], None)
            if pair.blocked and pair.sql and not pair.sql_result:
                if pair.lease_deadline - time.monotonic() > 5:
                    for _ in range(10):
                        if not await self._sql_accepts(pair.sql):
                            pair.sql_result = ('revoked' if pair.lease_deadline > time.monotonic() else 'expired')
                            break
                        await asyncio.sleep(.25)
                    else:
                        pair.sql_result = 'accepted'
                else:
                    pair.sql_result = 'expired'
                pair.sql = {}
            return pair.public()

    async def _clean(self, pair):
        for index, claims in enumerate(pair.claims):
            if (index == 0 and pair.blocked) or claims['exp'] <= time.time():
                continue
            status, _ = await self._request(pair, 'A' if index == 0 else 'B', self._token,
                                            revoke=payload_for(claims), phase='cleanup')
            if status not in (200, 204):
                raise AccessDenied('No se pudo limpiar la pareja anterior. Reintenta la limpieza.')
        pair.tokens.clear()
        pair.sql.clear()

    async def clear(self, session, mode):
        async with self._lock:
            pair = self._owned(session, mode)
            await self._clean(pair)
            self._pairs.pop((session.sid, mode), None)
