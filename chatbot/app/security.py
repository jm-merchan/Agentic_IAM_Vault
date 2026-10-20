"""OIDC sessions stay in server memory. JWTs never enter prompts or browser storage."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
import jwt
from .telemetry import operation, trace_id
from . import lab_capture
from opentelemetry import trace

TENANT = os.environ.get('VERIFY_TENANT', 'https://merchan.verify.ibm.com').rstrip('/')
ISSUER = TENANT + '/oauth2'
CALLBACK = 'http://localhost:8088/auth/callback'


class AccessDenied(Exception):
    """Safe user-facing authorization error."""


@dataclass
class Session:
    sid: str
    subject: str = ''
    name: str = ''
    groups: list[str] = field(default_factory=list)
    access_token: str = field(default='', repr=False)
    expires_at: float = 0
    state: str = field(default='', repr=False)
    nonce: str = field(default='', repr=False)
    verifier: str = field(default='', repr=False)
    login_started: float = 0
    messages: list = field(default_factory=list, repr=False)
    display_messages: list = field(default_factory=list, repr=False)
    events: list[dict] = field(default_factory=list)
    traces: list[str] = field(default_factory=list)
    pending: dict | None = None
    catalogue_evidence: dict | None = field(default=None, repr=False)
    application_draft: dict | None = field(default=None, repr=False)
    model_provider: str = ''
    language: str = 'es'

    def require_login(self):
        if not self.subject or time.time() >= self.expires_at:
            raise AccessDenied('La sesión ha caducado. Vuelve a entrar con Verify.')


def role_for_groups(groups: list[str], mapping: dict) -> str | None:
    membership = set(groups)
    if membership.intersection(mapping.get('readwrite', [])):
        return 'readwrite'
    if membership.intersection(mapping.get('readonly', [])):
        return 'readonly'
    if membership.intersection(mapping.get('sensitive', [])):
        return 'readonly'
    return None


class Identity:
    def __init__(self, config: dict):
        self.config = config
        self.sessions: dict[str, Session] = {}
        self.keys = jwt.PyJWKClient(ISSUER + '/jwks', cache_keys=True)

    def start(self) -> tuple[Session, str]:
        self.sessions = {k: v for k, v in self.sessions.items()
                         if max(v.expires_at, v.login_started + 600) > time.time()}
        session = Session(secrets.token_urlsafe(32))
        session.state = secrets.token_urlsafe(32)
        session.nonce = secrets.token_urlsafe(32)
        session.verifier = secrets.token_urlsafe(64)
        session.login_started = time.time()
        self.sessions[session.sid] = session
        challenge = base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest()).rstrip(b'=').decode()
        query = urlencode(dict(client_id=self.config['oidc']['client_id'], response_type='code',
                               redirect_uri=CALLBACK, scope='openid profile email', state=session.state,
                               nonce=session.nonce, code_challenge=challenge,
                               code_challenge_method='S256', prompt='login'))
        return session, ISSUER + '/authorize?' + query

    def validate(self, token: str, audience: str | None) -> dict:
        key = self.keys.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=['RS256'], issuer=ISSUER,
                          audience=audience, options={'verify_aud': audience is not None,
                                                     'require': ['iss', 'sub', 'exp', 'iat']}, leeway=15)

    @operation('verify.oidc_login')
    async def finish(self, sid: str, state: str, code: str) -> Session:
        pending = self.sessions.get(sid)
        if (not pending or not pending.state or not secrets.compare_digest(pending.state, state)
                or time.time() - pending.login_started > 600):
            raise AccessDenied('La solicitud de inicio de sesión no es válida o ha caducado.')
        pending.state = ''  # single use, including failed exchanges
        credential = self.config['oidc']
        data = dict(grant_type='authorization_code', code=code, redirect_uri=CALLBACK,
                    code_verifier=pending.verifier)
        lab_capture.request(trace.get_current_span(), 'POST', ISSUER + '/token', data,
                            basic_auth=(credential['client_id'], credential['client_secret']))
        async with httpx.AsyncClient(timeout=30) as client:
            result = await client.post(ISSUER + '/token', auth=(credential['client_id'], credential['client_secret']),
                                       data=data)
        trace.get_current_span().set_attribute('http.response.status_code', result.status_code)
        lab_capture.response(trace.get_current_span(), result)
        if result.status_code != 200:
            raise AccessDenied('Verify no ha aceptado el código de autorización.')
        token = result.json()
        claims = await asyncio.to_thread(self.validate, token['id_token'], credential['client_id'])
        access = await asyncio.to_thread(self.validate, token['access_token'], credential['client_id'])
        if not secrets.compare_digest(claims.get('nonce', ''), pending.nonce) or claims['sub'] != access['sub']:
            raise AccessDenied('No coincide la identidad de la respuesta OIDC.')
        if access.get('may_act', {}).get('client_id') != credential['client_id']:
            raise AccessDenied('El token no autoriza la delegación a este agente.')
        groups = access.get('groups', claims.get('groups', claims.get('groupIds', [])))
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise AccessDenied('Verify no ha emitido una lista de grupos válida.')
        session = Session(secrets.token_urlsafe(32), subject=access['sub'],
                          name=claims.get('name') or claims.get('preferred_username') or access['sub'],
                          groups=groups, access_token=token['access_token'],
                          expires_at=min(claims['exp'], access['exp']))
        self.sessions.pop(sid, None)
        self.sessions[session.sid] = session
        trace.get_current_span().set_attribute('user.id', session.subject)
        trace.get_current_span().set_attribute('user.role', role_for_groups(groups, self.config['runtime']['groups']) or 'none')
        session.traces.append(trace_id())
        return session


def load_config() -> dict:
    """Use a short-lived bootstrap token scoped only to chatbot client credentials."""
    token = os.environ.pop('CHATBOT_BOOTSTRAP_TOKEN', '')
    addr = os.environ.get('VAULT_ADDR', 'https://127.0.0.1:8443')
    ca = os.environ.get('VAULT_CACERT', '/tmp/vault/vault.ca')
    if not token:
        raise RuntimeError('Inicia la aplicación con bash chatbot/scripts/run.sh.')
    context = ssl.create_default_context(cafile=ca)
    config: dict = {'vault_addr': addr, 'vault_ca': ca}
    with httpx.Client(verify=context, timeout=30) as client:
        try:
            for name in ('oidc', 'research', 'sts', 'runtime'):
                res = client.get(addr + '/v1/secrets/data/chatbot/' + name,
                                 headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify'})
                if res.status_code != 200:
                    raise RuntimeError('Falta configuración de chatbot en Vault: ' + name)
                config[name] = res.json()['data']['data']
            # Explicitly optional: the UI and authorization tests work before the LLM is connected.
            res = client.get(addr + '/v1/secrets/data/chatbot/model',
                             headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify'})
            config['model'] = res.json()['data']['data'] if res.status_code == 200 else {}
            from .model_config import PROVIDER_LABELS
            profiles = config['model'].pop('providers', None)
            if profiles is None:
                provider = config['model'].get('provider')
                profiles = {provider: dict(config['model'])} if provider in PROVIDER_LABELS else {}
            if not isinstance(profiles, dict) or any(p not in PROVIDER_LABELS for p in profiles):
                raise RuntimeError('El catálogo de proveedores no es válido.')
            config['models'] = profiles
            config['model'].pop('api_key', None)
            for provider, profile in profiles.items():
                if not isinstance(profile, dict) or profile.get('provider') != provider:
                    raise RuntimeError('Perfil de proveedor no válido: ' + provider)
                profile.pop('api_key', None)
                res = client.get(addr + '/v1/secrets/data/chatbot/' + provider,
                                 headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify'})
                if res.status_code != 200:
                    raise RuntimeError('Configura el agente del proveedor: ' + provider)
                config[provider] = res.json()['data']['data']
            if profiles:
                default = config['model'].get('provider')
                if default not in profiles:
                    raise RuntimeError('El proveedor inicial no está en el catálogo.')
                config['model'] = dict(profiles[default])
        finally:
            client.post(addr + '/v1/auth/token/revoke-self',
                        headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify'})
    return config
