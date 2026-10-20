import asyncio
import json
import ssl
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security import AccessDenied, Session
from app.services import Services
from app.spiffe import OPENAI_AUDIENCE, OPENAI_RAR, SPIFFE_PATH
from app.telemetry import records_for, span, trace_id
from app.trace_content import SPIFFE_CONTENT_KEYS, VaultTraceRecorder


def service():
    obj = object.__new__(Services)
    obj.config = {'vault_addr': 'https://vault.local', 'model': {
        'provider': 'openai', 'model': 'gpt-4.1-mini', 'credential_source': 'vault_spiffe',
        'issuer': 'https://public.example/v1/verify/spiffe',
        'spiffe_id': 'spiffe://lumen.demo/ns/verify/agent/lumen-openai',
        'identity_provider_id': 'idp-test', 'service_account_id': 'svc_acct_test'}}
    obj.vault_tls = ssl.create_default_context()
    return obj, Session('test', subject='user', expires_at=time.time()+600)


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize('claim_override', [{}, {'sub': 'spiffe://lumen.demo/other'}, {'aud': 'other-api'},
                                           {'iss': 'https://untrusted.example'}, {'exp': 1}])
async def test_signed_svid_must_match_identity_audience_and_lifetime(monkeypatch, claim_override):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    obj, _ = service()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {'iss': obj.config['model']['issuer'], 'sub': obj.config['model']['spiffe_id'],
              'aud': [OPENAI_AUDIENCE], 'iat': int(time.time()), 'exp': int(time.time())+300, **claim_override}
    svid = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test'})
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk['kid'] = 'test'
    def handler(request):
        assert request.url.path == '/v1/spiffe/.well-known/keys'
        assert 'x-vault-token' not in request.headers
        assert request.headers['x-vault-namespace'] == 'verify'
        return httpx.Response(200, json={'keys': [jwk]})
    mock_http(monkeypatch, handler)
    obj.client_token = AsyncMock(return_value='verify-rar-jwt')
    obj.vault_post = AsyncMock(return_value={'data': {'token': svid}})
    if claim_override:
        with pytest.raises(AccessDenied, match='identidad SPIFFE'):
            await obj.mint_openai_identity()
    else:
        with span('test.svid.capture'):
            tid = trace_id()
            token, validated = await obj.mint_openai_identity()
        assert token == svid and validated == claims
        obj.vault_post.assert_awaited_once_with(SPIFFE_PATH, 'verify-rar-jwt', {'audience': OPENAI_AUDIENCE})
        attrs = next(r['attributes'] for r in records_for({tid}) if r['name'] == 'spiffe.mint_jwt_svid')
        assert json.loads(attrs['spiffe.jwt_svid']) == svid
        decoded = json.loads(attrs['spiffe.jwt_svid.decoded'])
        assert decoded['claims'] == claims and decoded['header']['kid'] == 'test'
        assert decoded['signature_verified'] is True
        assert attrs['spiffe.jwt_svid.truncated'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('status,remaining', [(200, 300), (200, 15), (401, 300)])
async def test_exchange_uses_svid_without_api_key_and_requires_usable_lifetime(monkeypatch, status, remaining):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    obj, _ = service()
    expiry = int(time.time())+remaining
    def handler(request):
        assert str(request.url) == 'https://auth.openai.com/oauth/token'
        assert 'authorization' not in request.headers
        payload = json.loads(request.content)
        assert payload['subject_token'] == 'signed-svid'
        assert payload['identity_provider_id'] == 'idp-test'
        assert payload['service_account_id'] == 'svc_acct_test'
        return httpx.Response(status, json={'access_token': 'temporary-test-token', 'token_type': 'Bearer', 'expires_at': expiry})
    mock_http(monkeypatch, handler)
    if status != 200 or remaining < 210:
        with pytest.raises(AccessDenied):
            await obj.exchange_openai_identity('signed-svid', {'exp': expiry})
    else:
        with span('test.svid.exchange'):
            tid = trace_id()
            token, deadline = await obj.exchange_openai_identity('signed-svid', {'exp': expiry})
        assert token == 'temporary-test-token'
        assert 290 < deadline-time.monotonic() <= 300
        attrs = next(r['attributes'] for r in records_for({tid}) if r['name'] == 'openai.token_exchange')
        assert json.loads(attrs['openai.exchange.subject_token']) == 'signed-svid'
        assert 'temporary-test-token' not in json.dumps(records_for({tid}))
        from app.lab_capture import STORE
        record = next(r for r in records_for({tid}) if r['name'] == 'openai.token_exchange')
        evidence = STORE.get(tid, record['span_id'])['sections']
        assert evidence['request']['value']['body']['subject_token'] == 'signed-svid'
        assert evidence['response']['value']['body']['access_token'] == token


def test_svid_capture_disabled_excludes_raw_token_and_claims(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '0')
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '1')
    with span('test.svid.disabled') as current:
        tid = trace_id()
        for key in SPIFFE_CONTENT_KEYS:
            VaultTraceRecorder().capture(current, key, 'SVID_CAPTURE_CANARY')
    encoded = json.dumps(records_for({tid}))
    assert 'SVID_CAPTURE_CANARY' not in encoded
    assert not SPIFFE_CONTENT_KEYS.intersection(records_for({tid})[0]['attributes'])


@pytest.mark.asyncio
async def test_each_run_reissues_identity_and_never_retains_provider_access_token():
    obj, session = service()
    obj.mint_openai_identity = AsyncMock(return_value=('jwt', {'exp': int(time.time())+300}))
    obj.exchange_openai_identity = AsyncMock(side_effect=[('one', time.monotonic()+300), ('two', time.monotonic()+300)])
    first, _ = await obj.model_credentials(session)
    second, _ = await obj.model_credentials(session)
    assert first['api_key'] == 'one' and second['api_key'] == 'two'
    assert obj.mint_openai_identity.await_count == 2
    assert 'api_key' not in obj.config['model']
    assert 'temporary-test-token' not in json.dumps(session.events)


@pytest.mark.asyncio
async def test_vault_denial_stops_before_openai_exchange():
    obj, session = service()
    obj.mint_openai_identity = AsyncMock(side_effect=AccessDenied('Vault 403'))
    obj.exchange_openai_identity = AsyncMock()
    with pytest.raises(AccessDenied, match='Vault 403'):
        await obj.model_credentials(session)
    obj.exchange_openai_identity.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_rar_for_spiffe_is_requested_and_checked(monkeypatch):
    from urllib.parse import parse_qs
    obj, _ = service()
    obj.config['openai'] = {'client_id': 'client', 'client_secret': 'test-only'}
    obj.identity = SimpleNamespace(validate=lambda *args: {'sub': 'client', 'authorization_details': OPENAI_RAR})
    def handler(request):
        assert json.loads(parse_qs(request.content.decode())['authorization_details'][0]) == OPENAI_RAR
        return httpx.Response(200, json={'access_token': 'rar-token'})
    mock_http(monkeypatch, handler)
    assert await obj.client_token('openai') == 'rar-token'
    obj.identity.validate = lambda *args: {'sub': 'other', 'authorization_details': OPENAI_RAR}
    with pytest.raises(AccessDenied, match='RAR'):
        await obj.client_token('openai')


@pytest.mark.parametrize('keys,selection,wanted', [
    ('XAI_MANAGEMENT_API_KEY=x', 'auto', 'xai'),
    ('OPENAI_ADMIN_API_KEY=o', 'auto', 'openai'),
    ('OPENAI_ADMIN_API_KEY=o XAI_MANAGEMENT_API_KEY=x', 'auto', 'openai'),
    ('OPENAI_ADMIN_API_KEY=o XAI_MANAGEMENT_API_KEY=x', 'xai', 'xai'),
    ('XAI_MANAGEMENT_API_KEY=x', 'openai', None),
    ('', 'auto', None),
    ('XAI_MANAGEMENT_API_KEY=x', 'anthropic', None),
])
def test_provider_selection(keys, selection, wanted):
    script = Path(__file__).resolve().parents[2]/'scripts/demo/model-provider.sh'
    result = subprocess.run(['/bin/bash', '-c', 'set -eu; fail(){ exit 7; }; source "$1"; select_model_provider; printf "%s" "$LUMEN_SELECTED_PROVIDER"',
                             'test', str(script)], env={'PATH': '/usr/bin:/bin', 'LUMEN_MODEL_PROVIDER': selection,
                                                      **dict(pair.split('=', 1) for pair in keys.split())}, capture_output=True, text=True)
    if wanted is None:
        assert result.returncode != 0
    else:
        assert result.returncode == 0 and result.stdout == wanted
