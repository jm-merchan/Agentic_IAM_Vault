"""Two explicit credential flows; no root token, passwords or JWTs in tool results."""
from __future__ import annotations

import asyncio
import json
import ssl
import time
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
import jwt
import pymysql

from .i18n import Translator
from .security import AccessDenied, Identity, ISSUER, Session, role_for_groups
from .model_config import model_config
from .telemetry import headers, operation, span, trace_id
from .trace_content import VaultTraceRecorder
from . import lab_capture
from .applications import ApplicationServices
from .spiffe import SpiffeModelServices, OPENAI_RAR, ANTHROPIC_RAR
from opentelemetry import trace


XAI_RAR = [
    {'type': 'vault:path_access', 'path': 'xai/creds/lumen', 'capabilities': ['read']},
    {'type': 'vault:path_access', 'path': 'secrets/data/chatbot/xai-access', 'capabilities': ['read']},
]


class VaultPermissionDenied(AccessDenied):
    """An actual HTTP 403 from Vault, distinct from network or service errors."""


@dataclass(frozen=True)
class ModelCredential:
    api_key: str = field(repr=False)
    lease_id: str
    api_key_id: str
    expires_at: float
    ttl: float
    renewable: bool
    generation: str = ''


class Services(ApplicationServices, SpiffeModelServices):
    def __init__(self, config: dict, identity: Identity):
        self.config, self.identity = config, identity
        self.vault_tls = ssl.create_default_context(cafile=config['vault_ca'])
        self._xai_credential: ModelCredential | None = None
        self._xai_lock = asyncio.Lock()

    def role(self, session: Session) -> str:
        session.require_login()
        role = role_for_groups(session.groups, self.config['runtime']['groups'])
        if role is None:
            raise AccessDenied('Tu grupo no tiene acceso a los datos de este laboratorio.')
        return role

    def event(self, session: Session, title: str, detail: str, status='ok'):
        session.events.append(dict(title=title, detail=detail, status=status,
                                   time=time.strftime('%H:%M:%S'), trace_id=trace_id()))
        session.events[:] = session.events[-30:]

    @operation('verify.client_credentials')
    async def client_token(self, credential_name: str) -> str:
        current = trace.get_current_span()
        current.set_attribute('agent.identity', 'chatbot-' + credential_name)
        current.set_attribute('auth.flow', 'client_credentials')
        cred = self.config[credential_name]
        data = {'grant_type': 'client_credentials', 'scope': 'openid profile email'}
        expected_rar = {'xai': XAI_RAR, 'openai': OPENAI_RAR, 'anthropic': ANTHROPIC_RAR}.get(credential_name)
        if expected_rar is not None:
            data['authorization_details'] = json.dumps(expected_rar)
            current.set_attribute('auth.rar.required', True)
        lab_capture.request(current, 'POST', ISSUER + '/token', data,
                            basic_auth=(cred['client_id'], cred['client_secret']))
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(ISSUER + '/token', auth=(cred['client_id'], cred['client_secret']),
                                         data=data)
        current.set_attribute('http.response.status_code', response.status_code)
        lab_capture.response(current, response)
        if response.status_code != 200:
            raise AccessDenied('No se ha podido autenticar al agente en Verify.')
        token = response.json()['access_token']
        if expected_rar is not None:
            claims = await asyncio.to_thread(self.identity.validate, token, None)
            if claims['sub'] != cred['client_id'] or claims.get('authorization_details') != expected_rar:
                raise AccessDenied('Verify no ha emitido el RAR esperado para el agente ' + credential_name + '.')
        return token

    @operation('verify.obo_exchange')
    async def exchange(self, session: Session, path: str, capabilities=None) -> str:
        current = trace.get_current_span()
        current.set_attribute('vault.path', path)
        current.set_attribute('auth.flow', 'obo')
        session.require_login()
        actor = await self.client_token('oidc')
        cred = self.config['sts']
        async with httpx.AsyncClient(timeout=30) as client:
            with span('verify.token_exchange', **{'vault.path': path, 'auth.flow': 'obo'}) as exchange_span:
                data = {
                    'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
                    'subject_token': session.access_token, 'subject_token_type': 'urn:ietf:params:oauth:token-type:access_token',
                    'actor_token': actor, 'actor_token_type': 'urn:ietf:params:oauth:token-type:access_token',
                    'requested_token_type': 'urn:ietf:params:oauth:token-type:access_token',
                    'authorization_details': json.dumps([{'type': 'vault:path_access', 'path': path,
                                                         'capabilities': capabilities or ['read']}]),
                }
                lab_capture.request(exchange_span, 'POST', ISSUER + '/token', data,
                                    basic_auth=(cred['client_id'], cred['client_secret']))
                response = await client.post(ISSUER + '/token', auth=(cred['client_id'], cred['client_secret']), data=data)
                exchange_span.set_attribute('http.response.status_code', response.status_code)
                lab_capture.response(exchange_span, response)
        current.set_attribute('http.response.status_code', response.status_code)
        if response.status_code != 200:
            raise AccessDenied('Verify ha rechazado la delegación OBO. Vuelve a iniciar sesión.')
        token = response.json()['access_token']
        # The Verify STS profile has no audience support in this lab. Validate signature,
        # issuer, expiry, subject, actor AND exact RAR before presenting the JWT to Vault.
        claims = await asyncio.to_thread(self.identity.validate, token, None)
        expected_rar = [{'type': 'vault:path_access', 'path': path, 'capabilities': capabilities or ['read']}]
        if (claims['sub'] != session.subject
                or claims.get('actor-token', {}).get('sub') != self.config['oidc']['client_id']
                or claims.get('authorization_details') != expected_rar):
            raise AccessDenied('La delegación recibida no coincide con la operación solicitada.')
        self.event(session, 'Delegación OBO', 'Usuario → Verify STS → agente · permiso para una ruta')
        return token

    @operation('vault.read')
    async def vault_get(self, path: str, token: str, *, params=None) -> dict:
        return await self._vault_request(path, token, params=params)

    @operation('vault.write')
    async def vault_post(self, path: str, token: str, payload: dict) -> dict:
        return await self._vault_request(path, token, 'POST', payload)

    async def _vault_request(self, path: str, token: str, method='GET', payload=None, *, params=None) -> dict:
        current = trace.get_current_span()
        current.set_attribute('vault.path', path)
        current.set_attribute('vault.namespace', 'verify')
        current.set_attribute('http.request.method', method)
        recorder = VaultTraceRecorder()
        current.set_attribute('vault.capture.raw', recorder.enabled)
        url = str(httpx.URL(self.config['vault_addr'] + '/v1/' + path).copy_merge_params(params or {}))
        request_headers = {'X-Vault-Token': token, 'X-Vault-Namespace': 'verify', **headers()}
        recorder.capture(current, 'vault.http.request', {
            'method': method, 'url': url, 'headers': request_headers, 'body': payload,
        })
        recorder.capture(current, 'vault.auth.jwt', token)
        if recorder.enabled:
            try:
                # Observability decoding is not an authentication decision. OBO validation
                # occurs in exchange(); Vault validates both OBO and autonomous tokens.
                recorder.capture(current, 'vault.auth.jwt.decoded', {
                    'header': jwt.get_unverified_header(token),
                    'claims': jwt.decode(token, options={'verify_signature': False}),
                    'signature_verified_by_decoder': False,
                })
            except jwt.InvalidTokenError:
                current.set_attribute('vault.auth.jwt.decode_error', 'InvalidTokenError')
        async with httpx.AsyncClient(verify=self.vault_tls, timeout=30) as client:
            response = await client.request(method, url, headers=request_headers, json=payload)
        current.set_attribute('http.response.status_code', response.status_code)
        if recorder.enabled:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            recorder.capture(current, 'vault.http.response', {
                'status_code': response.status_code, 'headers': dict(response.headers), 'body': body,
            })
        if response.status_code == 200:
            current.set_attribute('vault.request_id', response.json().get('request_id', ''))
        if response.status_code == 403:
            raise VaultPermissionDenied(f'Vault ha denegado esta operación (HTTP 403): {path}. Revisa los permisos o los bloqueos activos.')
        if response.status_code != 200:
            raise AccessDenied('El servicio de credenciales no está disponible para esta operación.')
        return response.json()

    @operation('model.credentials')
    async def model_credentials(self, session: Session) -> tuple[dict, float | None]:
        """Reuse a dynamic key only while it covers the next run and expiry margin."""
        session.require_login()
        config = model_config(self.config, session.model_provider)
        if config.get('provider') == 'openai':
            return await self.openai_credentials(session)
        if config.get('provider') == 'anthropic':
            return await self.anthropic_credentials(session)
        if config.get('provider') != 'xai':
            return config, None
        if config.get('credential_source') != 'vault_dynamic':
            raise AccessDenied('Configura el motor dinámico de xAI antes de usar el chat.')
        current = trace.get_current_span()
        path = 'xai/creds/lumen'
        current.set_attribute('agent.identity', 'chatbot-xai')
        current.set_attribute('auth.flow', 'client_credentials')
        current.set_attribute('vault.path', path)
        async with self._xai_lock:
            credential = self._xai_credential
            token = await self.client_token('xai')
            try:
                generation = await self.authorize_xai(token)
            except AccessDenied:
                self._xai_credential = None
                raise
            cache_hit = (credential is not None and credential.expires_at - time.monotonic() > 210
                         and credential.generation == generation)
            current.set_attribute('vault.credential.reauthorized', True)
            current.set_attribute('vault.credential.cache_hit', cache_hit)
            if not cache_hit:
                self._xai_credential = None
                current.set_attribute('vault.credential.refresh_reason',
                                      'expired_invalidated_or_denied' if credential else 'initial')
                if credential:
                    current.set_attribute('vault.lease.previous_id', credential.lease_id)
                issued_at = time.monotonic()
                response = await self.vault_get(path, token, params={'ttl': 300})
                data = response.get('data', {})
                ttl = response.get('lease_duration', 0)
                lease_id = response.get('lease_id', '')
                if (not isinstance(data.get('api_key'), str) or not data['api_key']
                        or not lease_id.startswith(path + '/') or not isinstance(ttl, (int, float)) or ttl <= 0):
                    raise AccessDenied('Vault no ha devuelto una credencial dinámica de xAI válida.')
                credential = ModelCredential(data['api_key'], lease_id, data.get('api_key_id', ''),
                                             issued_at + ttl, ttl, bool(response.get('renewable')), generation)
                if credential.expires_at - time.monotonic() <= 30:
                    raise AccessDenied('La credencial de xAI no tiene vigencia suficiente. Reintenta la consulta.')
                self._xai_credential = credential
                current.set_attribute('vault.credential.warning_count', len(response.get('warnings') or []))
        # The plugin has no Renew callback; acquire a replacement instead of
        # extending a Vault lease beyond the key's native expiration at xAI.
        deadline = min(time.monotonic() + 180, credential.expires_at - 30)
        current.set_attribute('vault.lease.id', credential.lease_id)
        current.set_attribute('vault.lease.duration_seconds', credential.ttl)
        current.set_attribute('vault.lease.remaining_seconds', max(0, int(credential.expires_at - time.monotonic())))
        current.set_attribute('vault.lease.renewable', credential.renewable)
        current.set_attribute('xai.api_key.id', credential.api_key_id)
        current.set_attribute('vault.credential.source', 'dynamic')
        config['api_key'] = credential.api_key
        self.event(session, 'xAI · clave temporal',
                   ('Credencial vigente reutilizada' if cache_hit else 'Nueva credencial emitida por Vault') +
                   f' · {max(0, int(credential.expires_at - time.monotonic()))} s restantes')
        return config, deadline

    @operation('model.authorization')
    async def authorize_xai(self, token: str) -> str:
        response = await self.vault_get('secrets/data/chatbot/xai-access', token)
        generation = response.get('data', {}).get('data', {}).get('generation')
        if not isinstance(generation, str) or not generation:
            raise AccessDenied('Falta la configuración de autorización de xAI en Vault.')
        return generation

    @operation('data.access')
    async def database(self, session: Session, statement: str, params=(), *, write=False):
        role = self.role(session)
        if write and role != 'readwrite':
            raise AccessDenied('Tu grupo solo permite consultar. No puedes modificar datos.')
        # Read-only queries never acquire RW credentials, even for the writer.
        credential_role = 'readwrite' if write else 'readonly'
        path = 'database/creds/chatbot-' + credential_role
        token = await self.exchange(session, path)
        credential = await self.vault_get(path, token)
        self.event(session, 'Credencial temporal', f'MySQL · {credential_role} · {credential["lease_duration"]} s')

        def execute():
            with pymysql.connect(host='127.0.0.1', port=13306, user=credential['data']['username'],
                                 password=credential['data']['password'], database='scripting',
                                 connect_timeout=10, read_timeout=20, write_timeout=20,
                                 cursorclass=pymysql.cursors.DictCursor, autocommit=False) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(statement, params)
                    if write:
                        connection.commit()
                        return {'affected_rows': cursor.rowcount, 'id': cursor.lastrowid}
                    rows = cursor.fetchmany(50)
                    return [{k: float(v) if isinstance(v, Decimal) else str(v) if hasattr(v, 'isoformat') else v
                             for k, v in row.items()} for row in rows]
        try:
            with span('mysql.query', **{'db.system.name': 'mysql', 'db.namespace': 'scripting',
                                       'db.operation.name': 'INSERT' if write else 'SELECT',
                                       'db.role': credential_role}) as current:
                lab_capture.capture(current, 'connection', 'Credencial dinámica utilizada en MySQL', {
                    'host': '127.0.0.1', 'port': 13306, 'database': 'scripting',
                    'username': credential['data']['username'], 'password': credential['data']['password'],
                    'lease_id': credential.get('lease_id'), 'lease_duration': credential.get('lease_duration'),
                    'renewable': credential.get('renewable'),
                })
                lab_capture.capture(current, 'query', 'Consulta y parámetros enviados', {
                    'statement': statement, 'parameters': params,
                })
                data = await asyncio.to_thread(execute)
                lab_capture.capture(current, 'result', 'Resultado de MySQL', data)
        except pymysql.MySQLError:
            raise AccessDenied('MySQL no ha permitido completar la operación.') from None
        self.event(session, 'Datos ' + ('actualizados' if write else 'consultados'), 'MySQL · sesión cerrada al terminar')
        return data

    async def plans(self, session: Session):
        session.catalogue_evidence = None
        plans = await self.database(session, 'SELECT id,name,description,price_kwh,renewable FROM energy_plans ORDER BY id')
        session.catalogue_evidence = {'checked_at': time.time(), 'trace_id': trace_id(), 'plans': plans}
        return plans

    async def requests(self, session: Session):
        return await self.database(session, 'SELECT id,plan_id,note,status,created_at FROM service_requests WHERE subject_id=%s ORDER BY id DESC LIMIT 20', (session.subject,))

    async def inventory(self, session: Session):
        return await self.database(session, 'SELECT ID,server_name FROM test_encryption ORDER BY ID DESC LIMIT 20')

    def prepare_request(self, session: Session, plan_id: int, note: str) -> dict:
        if self.role(session) != 'readwrite':
            raise AccessDenied('Tu grupo solo permite lectura.')
        if plan_id not in {1, 2, 3} or not 1 <= len(note.strip()) <= 500:
            raise AccessDenied('Selecciona un plan válido y una nota de hasta 500 caracteres.')
        session.pending = {'plan_id': plan_id, 'note': note.strip(), 'created_at': time.time()}
        if session.application_draft is not None:
            session.application_draft['form'].update(plan_id=plan_id, note=note.strip())
        return {'status': 'awaiting_user_confirmation', 'plan_id': plan_id,
                'note': note.strip(), 'message': 'Pulsa Continuar solicitud para completar los cinco pasos y revisar antes de guardar. No se contrata ningún suministro.'}

    async def confirm_request(self, session: Session):
        pending, session.pending = session.pending, None
        if not pending or time.time() - pending['created_at'] > 300:
            raise AccessDenied('El borrador no existe o ha caducado.')
        return await self.database(session, 'INSERT INTO service_requests(subject_id,plan_id,note) VALUES(%s,%s,%s)',
                                   (session.subject, pending['plan_id'], pending['note']), write=True)

    async def search(self, session: Session, topic: str):
        session.require_login()
        # Public topics keep private database data out of search-engine queries.
        topics = {'autoconsumo': 'qué es el autoconsumo solar compartido España',
                  'tarifas': 'CNMC entender tarifa eléctrica mercado libre regulado España',
                  'ahorro': 'IDAE consejos ahorro energía hogar eficiencia energética',
                  'movilidad': 'IDAE recarga vehículo eléctrico hogar España'}
        if topic not in topics:
            raise AccessDenied('Elige autoconsumo, tarifas, ahorro o movilidad para la búsqueda pública.')
        query = topics[topic]
        token = await self.client_token('research')
        secret = await self.vault_get('secrets/data/tavily', token)
        api_key = secret['data']['data']['TAVILY_API_KEY']
        self.event(session, 'Agente de investigación', 'Client Credentials → Agent Registry → secreto Tavily')
        with span('tavily.search', **{'search.topic': topic, 'server.address': 'api.tavily.com'}) as current:
            payload = {'query': query, 'max_results': 4, 'search_depth': 'basic',
                       'include_raw_content': False, 'include_answer': False}
            lab_capture.request(current, 'POST', 'https://api.tavily.com/search', payload,
                                headers={'Authorization': 'Bearer ' + api_key})
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post('https://api.tavily.com/search',
                                             headers={'Authorization': 'Bearer ' + api_key},
                                             json=payload)
            current.set_attribute('http.response.status_code', response.status_code)
            lab_capture.response(current, response)
        if response.status_code != 200:
            raise AccessDenied('La búsqueda web no está disponible en este momento.')
        self.event(session, 'Búsqueda web', 'Resultados públicos · credencial utilizada solo en el servidor')
        return [{'title': r['title'], 'url': r['url'], 'content': r.get('content', '')[:1800]}
                for r in response.json().get('results', [])]

    @operation('permissions.probe')
    async def permission_probe(self, session: Session, language=None):
        """Exercise exact OBO routes with synthetic data; never return credentials."""
        t = Translator(language or getattr(session, 'language', 'es'))
        role = self.role(session)
        reveal = self.can_reveal(session)
        fixture = self.config['runtime'].get('permission_probe', {})
        try:
            if fixture['version'] != 1 or not all(isinstance(value, str) and value for value in (
                fixture['profile_plaintext'], fixture['profile_ciphertext'],
                fixture['dni']['value'], fixture['dni']['token'],
                fixture['iban']['value'], fixture['iban']['token'])):
                raise ValueError('Invalid probe fixture')
        except (ValueError, KeyError, TypeError):
            raise AccessDenied('La comprobación de protección no está preparada. Revisa la instalación de la demo.') from None
        checks = []
        for suffix in ('readonly', 'readwrite'):
            path = 'database/creds/chatbot-' + suffix
            token = await self.exchange(session, path)
            try:
                await self.vault_get(path, token)
                allowed = True
            except VaultPermissionDenied:
                allowed = False
            expected = suffix == 'readonly' or role == 'readwrite'
            checks.append(('Base de datos y administración', path, allowed, expected))
        # Correct RAR for the forbidden path: agent ceiling + user ACL must still deny it.
        token = await self.exchange(session, 'secrets/data/verify-admin')
        try:
            await self.vault_get('secrets/data/verify-admin', token)
            allowed = True
        except VaultPermissionDenied:
            allowed = False
        checks.append(('Base de datos y administración', 'secrets/data/verify-admin', allowed, False))
        probes = [
            ('Transit · cifrar y descifrar el perfil', 'transit/encrypt/lumen-applications',
             {'plaintext': fixture['profile_plaintext']}, role == 'readwrite', 'ciphertext', None),
            ('Transit · cifrar y descifrar el perfil', 'transit/decrypt/lumen-applications',
             {'ciphertext': fixture['profile_ciphertext']}, reveal, 'plaintext', fixture['profile_plaintext']),
        ]
        for field in ('dni', 'iban'):
            name = 'lumen-' + field
            probes.extend([
                ('Transform · tokenizar y recuperar DNI e IBAN', 'transform/encode/' + name,
                 {'value': fixture[field]['value'], 'transformation': name}, role == 'readwrite', 'encoded_value', None),
                ('Transform · tokenizar y recuperar DNI e IBAN', 'transform/decode/' + name,
                 {'value': fixture[field]['token'], 'transformation': name}, reveal, 'decoded_value', fixture[field]['value']),
            ])
        for section, path, payload, expected, result_key, original in probes:
            # Always call Vault, including expected denials. RAR only grants the
            # precise update route; the user's policies still decide the result.
            token = await self.exchange(session, path, ['update'])
            try:
                data = (await self.vault_post(path, token, payload))['data']
                value = data.get(result_key)
                if not isinstance(value, str) or not value or (original is not None and value != original):
                    raise AccessDenied('Vault no ha devuelto el resultado ficticio esperado para la comprobación.')
                allowed = True
            except VaultPermissionDenied:
                allowed = False
            checks.append((section, path, allowed, expected))
        matches = sum(allowed == expected for _, _, allowed, expected in checks)
        current = trace.get_current_span()
        current.set_attribute('probe.check_count', len(checks))
        current.set_attribute('probe.matches_expected', matches == len(checks))
        self.event(session, 'Comprobación de límites',
                   f'{matches}/{len(checks)} resultados esperados · SQL, Transit y Transform · consulta la traza',
                   status='ok' if matches == len(checks) else 'error')
        lines = ['**' + t('Comprobación de permisos en Vault') + '**', '',
                 t('{matches} de {count} comprobaciones coinciden con los permisos esperados de tu perfil.', matches=matches, count=len(checks))]
        section = None
        for group, path, allowed, expected in checks:
            if group != section:
                section = group
                lines.extend(['', f'**{t(section)}**', '',
                              '| ' + t('Ruta de Vault') + ' | ' + t('Resultado') + ' | ' + t('Esperado') + ' |', '|---|---|---|'])
            lines.append(f'| `{path}` | {t("Permitido" if allowed else "Denegado")} | {t("Permitido" if expected else "Denegado")} |')
        lines.extend(['', t('Peticiones OBO reales con datos ficticios. El chat no muestra credenciales ni valores recuperados. '
                      'Las credenciales SQL caducan según su lease; Transform registra tokens de prueba cuando se permite tokenizar. '
                      'No se modifican solicitudes ni filas de MySQL.')])
        return '\n'.join(lines)
