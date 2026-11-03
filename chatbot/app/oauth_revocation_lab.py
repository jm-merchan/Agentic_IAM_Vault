"""Session-owned OAuth pairs; only lab-issued JWTs can reach the revoker."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import math
import os
import re
import time

import httpx
import pymysql
from opentelemetry.trace import Status, StatusCode

from .rar import authorization_details
from .security import AccessDenied, ISSUER
from .task_agents import actor_credential
from .telemetry import headers, span, trace_id
from .vault_clock import raise_for_clock_mismatch
from . import lab_capture

PATHS = {'delegated': 'database/creds/chatbot-readonly',
         'direct': 'xai/creds/lumen'}


def payload_for(claims, now=None):
    now = time.time() if now is None else now
    expiry = claims.get('exp')
    if (claims.get('iss') != ISSUER or not isinstance(claims.get('jti'), str)
            or not claims['jti'] or type(expiry) not in (int, float)
            or not math.isfinite(expiry) or expiry <= now):
        raise AccessDenied('El token del laboratorio ha caducado. Crea una pareja nueva.')
    return {'issuer': claims['iss'], 'unique_id': claims['jti'], 'exp': math.ceil(expiry - now) + 15}


@dataclass
class Credential:
    lease_id: str
    ttl: int
    deadline: float
    expires_at: float
    secret: dict = field(repr=False)
    state: str = 'active'
    before: str = ''
    after: str = ''
    before_expiry: bool = False

    def public(self):
        return dict(lease_id=self.lease_id, ttl=self.ttl, expires_at=self.expires_at,
                    state=self.state, before=self.before, after=self.after,
                    before_expiry=self.before_expiry)


@dataclass
class Pair:
    sid: str
    subject: str
    mode: str
    task_agent: str
    tokens: list = field(default_factory=list, repr=False)
    claims: list = field(default_factory=list, repr=False)
    credentials: list = field(default_factory=list, repr=False)
    accessed: bool = False
    blocked: bool = False
    token_verified: bool = False
    lease_verified: bool = False
    system_verified: bool = False
    verified: bool = False
    rows: list = field(default_factory=list)
    traces: list = field(default_factory=list)

    def public(self):
        def project(claims):
            result = {k: claims.get(k) for k in ('iss', 'jti', 'sub', 'exp')}
            if isinstance(claims.get('actor-token'), dict):
                result['actor-token'] = {'sub': claims['actor-token'].get('sub')}
            return result
        return dict(mode=self.mode, path=PATHS[self.mode], blocked=self.blocked, verified=self.verified,
                    tokens=[project(c) for c in self.claims], rows=list(self.rows), traces=list(self.traces),
                    accessed=self.accessed, leases=[c.public() for c in self.credentials],
                    token_verified=self.token_verified, lease_verified=self.lease_verified,
                    system_verified=self.system_verified)


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

    async def _operator_request(self, current, path, payload):
        """Inspect the real operator exchange without handing its bearer to the UI."""
        async with self._client() as client:
            request = client.build_request('POST', '/v1/' + path, json=payload, headers=headers())
            safe_headers = {key: '[REDACTED]' if key.lower() == 'x-vault-token' else value
                            for key, value in request.headers.items()}
            lab_capture.request(current, request.method, str(request.url), payload, headers=safe_headers)
            lab_capture.capture(current, 'replay_policy', 'Operador de revocación', {
                'allowed': False,
                'reason': 'La credencial del operador permanece en el servidor. Puedes inspeccionar esta llamada; su repetición desde la consola está desactivada.',
            })
            result = await client.send(request)
        lab_capture.capture(current, 'response', 'Respuesta recibida', {
            'status_code': result.status_code, 'headers': dict(result.headers),
            'body': result.json() if result.content else None,
        })
        return result

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
        # Telemetry contains metadata only. Detailed lab evidence stays in the
        # session-owned, ten-minute memory store; the operator bearer is excluded.
        with span('vault.write' if revoke is not None else 'vault.read', **{
            'vault.path': path, 'vault.namespace': 'verify', 'http.request.method': method,
            'agent.identity': actor, 'auth.flow': 'revocation_operator' if revoke else pair.mode,
            'revocation.lab.token': label, 'revocation.lab.phase': phase}) as current:
            index = 0 if label == 'A' else 1
            if len(pair.claims) > index:
                current.set_attribute('revocation.lab.seconds_until_exp', pair.claims[index]['exp'] - time.time())
                current.set_attribute('revocation.lab.unique_id', pair.claims[index]['jti'])
            if revoke is not None:
                result = await self._operator_request(current, path, revoke)
            else:
                request_headers = {'X-Vault-Token': token, 'X-Vault-Namespace': 'verify', **headers()}
                lab_capture.request(current, method, self.services.config['vault_addr'] + '/v1/' + path,
                                    None, headers=request_headers)
                async with self._client() as client:
                    result = await client.request(method, '/v1/' + path, headers=request_headers)
                lab_capture.response(current, result)
            current.set_attribute('http.response.status_code', result.status_code)
            body = result.json() if result.content else {}
            current.set_attribute('vault.request_id', body.get('request_id', ''))
            self._row(pair, label, phase, 'Vault', result.status_code)
            raise_for_clock_mismatch(result, token, current)
            return result.status_code, body

    @staticmethod
    def _row(pair, label, phase, target, status):
        pair.rows.append(dict(phase=phase, token=label, target=target,
                              status=status, trace_id=trace_id()))
        pair.rows[:] = pair.rows[-100:]

    async def _lookup(self, pair, index, phase):
        credential = pair.credentials[index]
        label = 'AB'[index]
        with span('vault.write', **{'vault.path': 'sys/leases/lookup', 'vault.namespace': 'verify',
                'http.request.method': 'POST', 'auth.flow': 'revocation_operator',
                'agent.identity': 'oauth-revocation-operator', 'vault.lease_id': credential.lease_id,
                'revocation.lab.token': label, 'revocation.lab.phase': phase}) as current:
            try:
                lookup_started, lookup_wall = time.monotonic(), time.time()
                response = await self._operator_request(current, 'sys/leases/lookup',
                                                        {'lease_id': credential.lease_id})
                current.set_attribute('http.response.status_code', response.status_code)
                body = response.json()
                ttl = body.get('data', {}).get('ttl')
                if (response.status_code == 200 and body.get('data', {}).get('id') == credential.lease_id
                        and type(ttl) in (int, float) and math.isfinite(ttl) and ttl > 0):
                    state = 'active'
                    if not pair.blocked:
                        # Bound expiry from request start; allow for whole-second
                        # rounding without adding response latency to the lease.
                        remaining = max(0, ttl - 1)
                        credential.deadline = min(credential.deadline, lookup_started + remaining)
                        credential.expires_at = min(credential.expires_at, lookup_wall + remaining)
                    current.set_attribute('vault.lease.ttl', ttl)
                elif (response.status_code in (400, 404)
                      and any(str(e).lower() in ('invalid lease', 'lease not found') for e in body.get('errors', []))):
                    state = 'missing'
                else:
                    state = 'unknown'
                self._row(pair, label, phase, 'Vault lease', f'{response.status_code} · {state}')
            except (httpx.HTTPError, ValueError):
                state = 'unknown'
                current.set_status(Status(StatusCode.ERROR))
                self._row(pair, label, phase, 'Vault lease', 'unavailable')
            credential.state = state
            current.set_attribute('revocation.lab.lease_state', state)
            return state

    async def _direct(self):
        credential = self.services.config.get('xai', {})
        if not credential.get('client_secret'):
            raise AccessDenied('El agente directo chatbot-xai no está configurado.')
        with span('verify.client_credentials', **{'agent.identity': 'chatbot-xai', 'auth.flow': 'client_credentials'}) as current:
            data = {'grant_type': 'client_credentials', 'scope': 'openid profile email',
                    'authorization_details': json.dumps(authorization_details(PATHS['direct'], ['read']))}
            lab_capture.request(current, 'POST', ISSUER + '/token', data,
                                basic_auth=(credential['client_id'], credential['client_secret']))
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(ISSUER + '/token',
                    auth=(credential['client_id'], credential['client_secret']),
                    data=data)
            lab_capture.response(current, response)
            current.set_attribute('http.response.status_code', response.status_code)
            if response.status_code != 200:
                raise AccessDenied('Verify no ha emitido el token directo del laboratorio.')
            return response.json()['access_token']

    async def _sql_accepts(self, credential, *, lease_id='', ttl=None, label='', phase=''):
        def connect():
            with span('mysql.query', **{'db.role': 'readonly', 'db.operation.name': 'SELECT',
                    'db.statement': 'SELECT 1', 'db.system.name': 'mysql',
                    'vault.lease_id': lease_id, 'revocation.lab.token': label,
                    'revocation.lab.phase': phase}) as current:
                lab_capture.capture(current, 'connection', 'Credencial dinámica utilizada en MySQL', {
                    'host': '127.0.0.1', 'port': 13306, 'database': None,
                    'username': credential['username'], 'password': credential['password'],
                    'lease_id': lease_id, 'lease_duration': ttl,
                })
                query = {'statement': 'SELECT 1', 'parameters': [], 'executed': False}
                lab_capture.capture(current, 'query', 'Consulta preparada', query)
                try:
                    with pymysql.connect(host='127.0.0.1', port=13306, connect_timeout=5,
                            user=credential['username'], password=credential['password']) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT 1')
                            query['executed'] = True
                            lab_capture.capture(current, 'query', 'Consulta y parámetros enviados', query)
                            row = cursor.fetchone()
                            lab_capture.capture(current, 'result', 'Resultado de MySQL', {'row': row})
                            return row[0] == 1
                except pymysql.MySQLError as exc:
                    lab_capture.capture(current, 'result', 'Resultado de MySQL', {
                        'error_code': exc.args[0], 'message': str(exc.args[1]) if len(exc.args) > 1 else '',
                        'query_executed': query['executed'],
                    })
                    if exc.args[0] not in (1045, 3118):
                        raise AccessDenied('No se pudo comprobar la conexión MySQL.') from None
                    current.set_attribute('db.error.code', exc.args[0])
                    current.set_status(Status(StatusCode.ERROR))
                    return False
        return await asyncio.to_thread(connect)

    async def _system(self, pair, index, phase):
        credential = pair.credentials[index]
        target, label = ('MySQL' if pair.mode == 'delegated' else 'xAI'), 'AB'[index]
        try:
            if pair.mode == 'delegated':
                accepted = await self._sql_accepts(credential.secret, lease_id=credential.lease_id,
                                                 ttl=credential.ttl, label=label, phase=phase)
                status = 'SQL OK' if accepted else 'SQL authentication rejected'
            else:
                # Authentication-only endpoint: no inference, prompt or cached chat key.
                with span('xai.auth_probe', **{'http.request.method': 'GET',
                        'server.address': 'api.x.ai', 'url.path': '/v1/api-key',
                        'revocation.lab.token': label, 'revocation.lab.phase': phase}) as current:
                    request_headers = {'Authorization': 'Bearer ' + credential.secret['api_key']}
                    lab_capture.request(current, 'GET', 'https://api.x.ai/v1/api-key', None,
                                        headers=request_headers)
                    async with httpx.AsyncClient(timeout=15) as client:
                        response = await client.get('https://api.x.ai/v1/api-key',
                                                    headers=request_headers)
                    lab_capture.response(current, response)
                    current.set_attribute('http.response.status_code', response.status_code)
                    accepted = True if response.status_code == 200 else None
                    if response.status_code in (401, 403):
                        accepted = False
                    elif response.status_code == 400:
                        body = response.json()
                        error = body.get('error', body.get('message', ''))
                        message = str(error.get('message', '') if isinstance(error, dict) else error)
                        if (re.search(r'api.?key|authentication', message, re.I)
                                and re.search(r'incorrect|invalid|expired|deleted|not found|does not exist', message, re.I)):
                            accepted = False
                    authentication = 'accepted' if accepted is True else 'rejected' if accepted is False else 'unknown'
                    current.set_attribute('revocation.lab.authentication', authentication)
                    status = f'HTTP {response.status_code} · {authentication}'
        except (httpx.HTTPError, AccessDenied, ValueError):
            accepted, status = None, 'unavailable'
        self._row(pair, label, phase, target, status)
        setattr(credential, 'before' if phase == 'system_before' else 'after',
                'accepted' if accepted is True else 'rejected' if accepted is False else 'unknown')
        return accepted

    @staticmethod
    def _fresh(pair, *, leases=False):
        if len(pair.tokens) != 2 or min(c['exp'] for c in pair.claims) - time.time() <= 30:
            raise AccessDenied('Quedan menos de 30 segundos. Crea otra pareja para distinguir bloqueo y caducidad.')
        if leases and (len(pair.credentials) != 2 or min(c.deadline for c in pair.credentials) - time.monotonic() <= 15):
            raise AccessDenied('Quedan menos de 15 segundos de lease. Crea otra pareja para distinguir revocación y caducidad.')

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
                    ttl, lease_id = response.get('lease_duration'), response.get('lease_id', '')
                    secret = response.get('data', {})
                    required = ('username', 'password') if mode == 'delegated' else ('api_key',)
                    if (not lease_id.startswith(PATHS[mode] + '/') or type(ttl) is not int or ttl <= 15
                            or not all(isinstance(secret.get(k), str) and secret[k] for k in required)):
                        raise AccessDenied('Vault no ha emitido un lease y una credencial válidos.')
                    pair.credentials.append(Credential(lease_id, ttl, time.monotonic() + ttl,
                                                        time.time() + ttl, {k: secret[k] for k in required}))
                    if await self._lookup(pair, index, 'lease_before') != 'active':
                        raise AccessDenied('No se pudo confirmar el lease activo en Vault.')
                return pair.public()
            except Exception:
                await self._clean(pair)
                self._pairs.pop(key, None)
                raise

    async def access(self, session, mode):
        async with self._lock:
            pair = self._owned(session, mode)
            self._remember(pair)
            if pair.blocked:
                raise AccessDenied('Crea otra pareja para probar el acceso inicial.')
            self._fresh(pair, leases=True)
            results = [await self._system(pair, i, 'system_before') for i in range(2)]
            pair.accessed = all(result is True for result in results)
            if not pair.accessed:
                raise AccessDenied('El acceso inicial al sistema final no funciona con ambas credenciales. Revisa la traza.')
            return pair.public()

    async def block(self, session, mode):
        async with self._lock:
            pair = self._owned(session, mode)
            self._remember(pair)
            if pair.blocked:
                return pair.public()
            self._fresh(pair, leases=True)
            if not pair.accessed:
                raise AccessDenied('Comprueba primero el acceso al sistema final con A y B.')
            for index in range(2):
                if await self._lookup(pair, index, 'lease_before') != 'active':
                    raise AccessDenied('Los leases deben seguir activos antes de revocar A.')
            self._fresh(pair, leases=True)
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
            self._fresh(pair)
            if not pair.blocked:
                raise AccessDenied('Bloquea primero el token A.')
            statuses = []
            for index, label in enumerate(('A', 'B')):
                status, _ = await self._request(pair, label, pair.tokens[index], phase='after')
                statuses.append(status)
            pair.token_verified = bool(pair.blocked and statuses == [403, 200]
                                 and min(c['exp'] for c in pair.claims) - time.time() > 30)
            if pair.token_verified:
                # Local signature verification intentionally still succeeds after Vault's denylist.
                await asyncio.to_thread(self.services.identity.validate, pair.tokens[0], None)
            for attempt in range(8):
                state = await self._lookup(pair, 0, 'lease_after')
                accepted = await self._system(pair, 0, 'system_after')
                if (state == 'missing' and accepted is False) or pair.credentials[0].deadline <= time.monotonic():
                    break
                if attempt < 7:
                    await asyncio.sleep(.5)
            b_state = await self._lookup(pair, 1, 'lease_after')
            b_accepted = await self._system(pair, 1, 'system_after')
            # Expiry, lookup errors and backend outages are never revocation evidence.
            a, b = pair.credentials
            a.before_expiry = a.deadline > time.monotonic()
            b.before_expiry = b.deadline > time.monotonic()
            timely = a.before_expiry and b.before_expiry
            pair.lease_verified = bool(timely and state == 'missing' and b_state == 'active')
            pair.system_verified = bool(timely and pair.accessed and accepted is False and b_accepted is True)
            pair.verified = bool(pair.token_verified and pair.lease_verified and pair.system_verified
                                 and min(c['exp'] for c in pair.claims) - time.time() > 30)
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
        for credential in pair.credentials:
            credential.secret.clear()

    async def clear(self, session, mode):
        async with self._lock:
            pair = self._owned(session, mode)
            await self._clean(pair)
            self._pairs.pop((session.sid, mode), None)
