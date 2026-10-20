import json
import ssl
import time
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from anthropic._models import FinalRequestOptions
from cryptography.hazmat.primitives.asymmetric import rsa

from app.agent import make_model
from app.security import AccessDenied, Session
from app.services import Services
from app.spiffe import ANTHROPIC_AUDIENCE, ANTHROPIC_SPIFFE_PATH
from app.telemetry import span, trace_id, records_for


def service():
    obj = object.__new__(Services)
    obj.config = {'vault_addr': 'https://vault.local', 'model': {
        'provider': 'anthropic', 'model': 'claude-haiku-5-5', 'credential_source': 'vault_spiffe',
        'issuer': 'https://public.example/v1/verify/spiffe',
        'spiffe_id': 'spiffe://lumen.demo/ns/verify/agent/lumen-anthropic',
        'federation_rule_id': 'fdrl_test', 'organization_id': 'org-test',
        'service_account_id': 'svac_test', 'workspace_id': 'wrkspc_test'}}
    obj.vault_tls = ssl.create_default_context()
    return obj, Session('test', subject='user', expires_at=time.time()+600)


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize('override', [{}, {'sub': 'spiffe://lumen.demo/ns/verify/agent/lumen-openai'},
                                      {'aud': 'https://api.openai.com/v1'}, {'iss': 'https://other.example'}, {'exp': 1}])
async def test_claude_requires_its_own_signed_identity(monkeypatch, override):
    obj, _ = service()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {'iss': obj.config['model']['issuer'], 'sub': obj.config['model']['spiffe_id'],
              'aud': [ANTHROPIC_AUDIENCE], 'iat': int(time.time()), 'exp': int(time.time())+300,
              'jti': 'unique-assertion', **override}
    svid = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test'})
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())); jwk['kid'] = 'test'
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={'keys': [jwk]}))
    obj.client_token = AsyncMock(return_value='verify-rar')
    obj.vault_post = AsyncMock(return_value={'data': {'token': svid}})
    if override:
        with pytest.raises(AccessDenied): await obj.mint_anthropic_identity()
    else:
        actual, validated = await obj.mint_anthropic_identity()
        assert actual == svid and validated == claims
        obj.client_token.assert_awaited_once_with('anthropic')
        obj.vault_post.assert_awaited_once_with(ANTHROPIC_SPIFFE_PATH, 'verify-rar', {'audience': ANTHROPIC_AUDIENCE})


@pytest.mark.asyncio
@pytest.mark.parametrize('status,ttl,scope', [(200, 300, 'workspace:developer'), (200, 60, 'workspace:developer'),
                                           (200, True, 'workspace:developer'), (200, 300, 'org:admin'),
                                           (401, 300, 'workspace:developer')])
async def test_exchange_protocol_lifetime_scope_and_safe_tracing(monkeypatch, status, ttl, scope):
    obj, _ = service(); calls = []
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://api.anthropic.com/v1/oauth/token'
        assert 'authorization' not in request.headers and 'x-api-key' not in request.headers
        assert json.loads(request.content) == {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': 'signed-svid',
            'federation_rule_id': 'fdrl_test', 'organization_id': 'org-test',
            'service_account_id': 'svac_test', 'workspace_id': 'wrkspc_test'}
        return httpx.Response(status, json={'access_token': 'PROVIDER-TOKEN-CANARY', 'token_type': 'Bearer',
                                           'expires_in': ttl, 'scope': scope})
    mock_http(monkeypatch, handle)
    with span('test.claude.exchange'):
        tid = trace_id()
        if status != 200 or type(ttl) is not int or ttl <= 210 or scope != 'workspace:developer':
            with pytest.raises(AccessDenied): await obj.exchange_anthropic_identity('signed-svid', {})
        else:
            token, deadline = await obj.exchange_anthropic_identity('signed-svid', {})
            assert token == 'PROVIDER-TOKEN-CANARY' and 290 < deadline-time.monotonic() <= 300
    assert len(calls) == 1  # No implicit replay on a denied assertion.
    assert 'PROVIDER-TOKEN-CANARY' not in json.dumps(records_for({tid}))
    attrs = next(r['attributes'] for r in records_for({tid}) if r['name'] == 'anthropic.token_exchange')
    assert json.loads(attrs['anthropic.exchange.assertion']) == 'signed-svid'
    from app.lab_capture import STORE
    record = next(r for r in records_for({tid}) if r['name'] == 'anthropic.token_exchange')
    evidence = STORE.get(tid, record['span_id'])['sections']
    assert evidence['request']['value']['body'] == json.loads(calls[0].content)
    assert evidence['response']['value']['status_code'] == status
    assert evidence['response']['value']['body']['access_token'] == 'PROVIDER-TOKEN-CANARY'


def test_adapter_sends_only_bearer_even_with_an_ambient_api_key(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'ambient-must-not-be-used')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'ambient-token-must-not-be-used')
    model = make_model({'provider': 'anthropic', 'model': 'test', 'credential_source': 'vault_spiffe',
                        'api_key': 'temporary-federated-token'})
    for client in (model._client, model._async_client):
        req = client._build_request(FinalRequestOptions.construct(method='get', url='/v1/models'))
        assert req.headers['authorization'] == 'Bearer temporary-federated-token'
        assert 'x-api-key' not in req.headers
    with pytest.raises(AccessDenied):
        make_model({'provider': 'anthropic', 'model': 'test', 'api_key': 'static-key'})


@pytest.mark.asyncio
async def test_each_run_issues_another_svid_without_mutating_stored_config():
    obj, session = service()
    obj.mint_anthropic_identity = AsyncMock(side_effect=[('svid-one', {}), ('svid-two', {})])
    obj.exchange_anthropic_identity = AsyncMock(side_effect=[('token-one', time.monotonic()+300),
                                                           ('token-two', time.monotonic()+300)])
    first, _ = await obj.model_credentials(session)
    second, _ = await obj.model_credentials(session)
    assert first['api_key'] != second['api_key']
    assert obj.mint_anthropic_identity.await_count == 2
    assert 'api_key' not in obj.config['model']
