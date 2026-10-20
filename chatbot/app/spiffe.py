"""Vault-issued SPIFFE identity exchanged for a provider access token per run."""
from __future__ import annotations

import time
import httpx
import jwt
from opentelemetry import trace

from .security import AccessDenied
from .model_config import model_config
from .telemetry import operation, span
from .trace_content import VaultTraceRecorder
from . import lab_capture

OPENAI_AUDIENCE = 'https://api.openai.com/v1'
SPIFFE_PATH = 'spiffe/role/lumen-openai/mintjwt'
OPENAI_RAR = [{'type': 'vault:path_access', 'path': SPIFFE_PATH, 'capabilities': ['update']}]
ANTHROPIC_AUDIENCE = 'https://api.anthropic.com'
ANTHROPIC_SPIFFE_PATH = 'spiffe/role/lumen-anthropic/mintjwt'
ANTHROPIC_RAR = [{'type': 'vault:path_access', 'path': ANTHROPIC_SPIFFE_PATH, 'capabilities': ['update']}]


class SpiffeModelServices:
    async def mint_openai_identity(self) -> tuple[str, dict]:
        return await self._mint_model_identity('openai', OPENAI_AUDIENCE, SPIFFE_PATH)

    async def mint_anthropic_identity(self) -> tuple[str, dict]:
        return await self._mint_model_identity('anthropic', ANTHROPIC_AUDIENCE, ANTHROPIC_SPIFFE_PATH)

    @operation('spiffe.mint_jwt_svid')
    async def _mint_model_identity(self, provider: str, audience: str, path: str) -> tuple[str, dict]:
        config = model_config(self.config, provider)
        token = await self.client_token(provider)
        response = await self.vault_post(path, token, {'audience': audience})
        svid = response.get('data', {}).get('token', '')
        if not isinstance(svid, str) or not svid:
            raise AccessDenied('Vault no ha emitido un JWT-SVID válido.')
        # Verify locally with Vault's public keys, in addition to the provider's validation.
        async with httpx.AsyncClient(verify=self.vault_tls, timeout=15) as client:
            with span('vault.jwks', **{'vault.path': 'spiffe/.well-known/keys',
                                     'vault.namespace': 'verify', 'http.request.method': 'GET'}) as keys_span:
                lab_capture.request(keys_span, 'GET', self.config['vault_addr'] + '/v1/spiffe/.well-known/keys',
                                    None, headers={'X-Vault-Namespace': 'verify'})
                jwks = await client.get(self.config['vault_addr'] + '/v1/spiffe/.well-known/keys',
                                        headers={'X-Vault-Namespace': 'verify'})
                keys_span.set_attribute('http.response.status_code', jwks.status_code)
                lab_capture.response(keys_span, jwks)
        if jwks.status_code != 200:
            raise AccessDenied('No se han podido obtener las claves públicas SPIFFE de Vault.')
        try:
            header = jwt.get_unverified_header(svid)
            keys = jwt.PyJWKSet.from_dict(jwks.json())
            key = next(k for k in keys.keys if k.key_id == header.get('kid'))
            claims = jwt.decode(svid, key.key, algorithms=['RS256'], issuer=config['issuer'],
                                audience=audience, options={'require': ['iss', 'sub', 'aud', 'iat', 'exp']})
            if claims['sub'] != config['spiffe_id'] or claims['aud'] not in (audience, [audience]):
                raise ValueError('Unexpected workload or audience')
        except (jwt.PyJWTError, ValueError, KeyError, StopIteration):
            raise AccessDenied('El JWT-SVID no corresponde a la identidad SPIFFE configurada.') from None
        current = trace.get_current_span()
        for name, value in {'spiffe.id': claims['sub'], 'spiffe.issuer': claims['iss'],
                            'spiffe.audience': audience, 'spiffe.jwt.kid': header['kid'],
                            'spiffe.jwt.jti': claims.get('jti', ''), 'spiffe.jwt.expires_at': claims['exp'],
                            'spiffe.jwt.issued_at': claims['iat'], 'spiffe.jwt.signature_verified': True}.items():
            current.set_attribute(name, value)
        recorder = VaultTraceRecorder()
        recorder.capture(current, 'spiffe.jwt_svid', svid)
        recorder.capture(current, 'spiffe.jwt_svid.decoded', {
            'header': header, 'claims': claims, 'signature_verified': True,
            'validated_by': 'Lumen / PyJWT / Vault JWKS',
        })
        return svid, claims

    @operation('openai.token_exchange')
    async def exchange_openai_identity(self, svid: str, claims: dict) -> tuple[str, float]:
        config = model_config(self.config, 'openai')
        current = trace.get_current_span()
        current.set_attribute('auth.flow', 'spiffe_jwt_svid')
        current.set_attribute('openai.identity_provider_id', config['identity_provider_id'])
        current.set_attribute('openai.service_account_id', config['service_account_id'])
        VaultTraceRecorder().capture(current, 'openai.exchange.subject_token', svid)
        payload = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
            'subject_token_type': 'urn:ietf:params:oauth:token-type:jwt',
            'subject_token': svid, 'identity_provider_id': config['identity_provider_id'],
            'service_account_id': config['service_account_id'],
        }
        lab_capture.request(current, 'POST', 'https://auth.openai.com/oauth/token', payload)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post('https://auth.openai.com/oauth/token', json=payload)
        current.set_attribute('http.response.status_code', response.status_code)
        lab_capture.response(current, response)
        if response.status_code != 200:
            raise AccessDenied(f'OpenAI ha rechazado el intercambio SPIFFE (HTTP {response.status_code}). Revisa el proveedor y su mapping.')
        data = response.json()
        token, expires = data.get('access_token'), data.get('expires_at')
        if (not isinstance(token, str) or not token or data.get('token_type', '').lower() != 'bearer'
                or not isinstance(expires, (int, float))):
            raise AccessDenied('OpenAI no ha devuelto un token temporal válido.')
        expires = min(expires, claims['exp'])
        remaining = expires - time.time()
        if remaining <= 210:
            raise AccessDenied('El token SPIFFE/OpenAI no tiene vigencia suficiente para iniciar la consulta.')
        current.set_attribute('openai.token.expires_at', expires)
        current.set_attribute('openai.token.remaining_seconds', int(remaining))
        return token, time.monotonic() + remaining

    async def openai_credentials(self, session):
        session.require_login()
        config = model_config(self.config, 'openai')
        if config.get('credential_source') != 'vault_spiffe':
            raise AccessDenied('Configura OpenAI mediante SPIFFE JWT-SVID antes de usar el chat.')
        # Every run gets a fresh SVID and exchanges it. No refresh token or static fallback.
        svid, claims = await self.mint_openai_identity()
        token, expires = await self.exchange_openai_identity(svid, claims)
        config['api_key'] = token  # SDK Bearer credential slot; this is a short-lived WIF access token.
        current = trace.get_current_span()
        current.set_attribute('model.provider', 'openai')
        current.set_attribute('vault.credential.source', 'spiffe_jwt_svid')
        self.event(session, 'OpenAI · SPIFFE JWT-SVID', 'Vault → identidad firmada → OpenAI token exchange · token temporal')
        return config, min(time.monotonic() + 180, expires - 30)

    @operation('anthropic.token_exchange')
    async def exchange_anthropic_identity(self, svid: str, claims: dict) -> tuple[str, float]:
        config = model_config(self.config, 'anthropic')
        current = trace.get_current_span()
        current.set_attribute('auth.flow', 'spiffe_jwt_svid')
        for field in ('federation_rule_id', 'organization_id', 'service_account_id', 'workspace_id'):
            current.set_attribute('anthropic.' + field, config[field])
        VaultTraceRecorder().capture(current, 'anthropic.exchange.assertion', svid)
        # A JWT carrying jti is single-use at Anthropic. Never retry the assertion.
        started = time.monotonic()
        payload = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': svid,
            **{field: config[field] for field in ('federation_rule_id', 'organization_id',
                                                 'service_account_id', 'workspace_id')},
        }
        lab_capture.request(current, 'POST', 'https://api.anthropic.com/v1/oauth/token', payload,
                            headers={'anthropic-version': '2023-06-01'})
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post('https://api.anthropic.com/v1/oauth/token',
                                        headers={'anthropic-version': '2023-06-01'}, json=payload)
        current.set_attribute('http.response.status_code', response.status_code)
        lab_capture.response(current, response)
        if response.status_code != 200:
            raise AccessDenied(f'Claude ha rechazado la federación SPIFFE (HTTP {response.status_code}). Revisa la regla y sus eventos de autenticación.')
        data = response.json()
        token, ttl = data.get('access_token'), data.get('expires_in')
        if (not isinstance(token, str) or not token or data.get('token_type', '').lower() != 'bearer'
                or type(ttl) not in (int, float) or data.get('scope') != 'workspace:developer'):
            raise AccessDenied('Claude no ha devuelto un token temporal con el alcance esperado.')
        expires = started + ttl
        remaining = expires - time.monotonic()
        if remaining <= 210:
            raise AccessDenied('El token de Claude no tiene vigencia suficiente para iniciar la consulta.')
        current.set_attribute('anthropic.token.remaining_seconds', int(remaining))
        current.set_attribute('anthropic.token.scope', data['scope'])
        return token, expires

    async def anthropic_credentials(self, session):
        session.require_login()
        config = model_config(self.config, 'anthropic')
        if config.get('credential_source') != 'vault_spiffe':
            raise AccessDenied('Configura Claude mediante SPIFFE JWT-SVID antes de usar el chat.')
        svid, claims = await self.mint_anthropic_identity()
        token, expires = await self.exchange_anthropic_identity(svid, claims)
        config['api_key'] = token  # Internal credential slot; the adapter sends Bearer, never x-api-key.
        current = trace.get_current_span()
        current.set_attribute('model.provider', 'anthropic')
        current.set_attribute('vault.credential.source', 'spiffe_jwt_svid')
        self.event(session, 'Claude · SPIFFE JWT-SVID', 'Vault → identidad de un solo uso → Claude · token temporal')
        return config, min(time.monotonic() + 180, expires - 30)
