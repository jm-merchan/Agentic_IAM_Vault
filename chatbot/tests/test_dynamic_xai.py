import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.security import AccessDenied, Session, load_config
from app.services import Services, VaultPermissionDenied, XAI_RAR
from app.telemetry import records_for, span, trace_id


def service_and_session():
    services = object.__new__(Services)
    services.config = {'model': {'provider': 'xai', 'model': 'grok-4.3',
                                  'credential_source': 'vault_dynamic'}}
    services._xai_credential = None
    services._xai_lock = asyncio.Lock()
    services.authorize_xai = AsyncMock(return_value='')
    return services, Session('session', subject='reader', expires_at=time.time() + 600)


@pytest.mark.asyncio
async def test_reuse_and_replacement_before_expiry_with_agent_identity():
    services, session = service_and_session()
    calls = []

    async def token(name):
        calls.append(name)
        return 'agent-jwt'

    async def read(path, jwt, *, params):
        assert (path, jwt, params) == ('xai/creds/lumen', 'agent-jwt', {'ttl': 300})
        return {'data': {'api_key': 'canary-' + str(len(calls)), 'api_key_id': 'key-id'},
                'lease_id': 'xai/creds/lumen/lease-' + str(len(calls)), 'lease_duration': 300}

    services.client_token, services.vault_get = token, read
    with span('test.dynamic'):
        tid = trace_id()
        first, deadline = await services.model_credentials(session)
        second, _ = await services.model_credentials(session)
        assert first['api_key'] == second['api_key']
        assert calls == ['xai', 'xai']
        assert services.authorize_xai.await_count == 2
        services._xai_credential = replace(services._xai_credential, expires_at=time.monotonic() + 200)
        third, _ = await services.model_credentials(session)
    assert calls == ['xai', 'xai', 'xai']
    assert first['api_key'] != third['api_key']
    assert 175 < deadline - time.monotonic() <= 180
    assert 'api_key' not in services.config['model']
    assert all('canary-' not in json.dumps(event) for event in session.events)
    spans = records_for({tid})
    assert sum(r['name'] == 'model.credentials' for r in spans) == 3
    assert [r['attributes']['vault.credential.cache_hit'] for r in spans if r['name'] == 'model.credentials'] == [False, True, False]
    assert 'canary-' not in json.dumps(spans)


@pytest.mark.asyncio
async def test_concurrent_runs_share_one_mint():
    services, session = service_and_session()
    calls = []
    async def token(_):
        await asyncio.sleep(0)
        return 'jwt'
    async def read(*args, **kwargs):
        calls.append('mint')
        return {'data': {'api_key': 'canary'}, 'lease_id': 'xai/creds/lumen/lease', 'lease_duration': 300}
    services.client_token, services.vault_get = token, read
    responses = await asyncio.gather(*(services.model_credentials(session) for _ in range(10)))
    assert calls == ['mint']
    assert all(config['api_key'] == 'canary' for config, _ in responses)
    assert services.authorize_xai.await_count == 10


@pytest.mark.asyncio
async def test_blocked_cached_key_is_discarded_and_real_vault_denial_is_returned():
    services, session = service_and_session()
    from app.services import ModelCredential
    services._xai_credential = ModelCredential('cached-key', 'xai/creds/lumen/id', 'id', time.monotonic()+300, 300, False)
    services.client_token = AsyncMock(return_value='rar-jwt')
    services.authorize_xai = AsyncMock(side_effect=VaultPermissionDenied('HTTP 403'))
    services.vault_get = AsyncMock()
    with pytest.raises(VaultPermissionDenied, match='403'):
        await services.model_credentials(session)
    assert services._xai_credential is None
    services.vault_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_block_unblock_without_a_ui_request_does_not_reuse_revoked_key():
    services, session = service_and_session()
    from app.services import ModelCredential
    services._xai_credential = ModelCredential('revoked', 'xai/creds/lumen/old', 'old', time.monotonic()+300, 300, False)
    services.authorize_xai = AsyncMock(return_value='new-generation')
    services.client_token = AsyncMock(return_value='rar-jwt')
    services.vault_get = AsyncMock(return_value={'data': {'api_key': 'new'}, 'lease_id': 'xai/creds/lumen/new', 'lease_duration': 300})
    config, _ = await services.model_credentials(session)
    assert config['api_key'] == 'new'


@pytest.mark.asyncio
async def test_authorization_gate_uses_real_vault_read_and_rejects_missing_generation():
    services, _ = service_and_session()
    services.vault_get = AsyncMock(return_value={'data': {'data': {'generation': 'epoch'}}})
    assert await Services.authorize_xai(services, 'jwt') == 'epoch'
    services.vault_get.assert_awaited_once_with('secrets/data/chatbot/xai-access', 'jwt')
    services.vault_get.return_value = {'data': {'data': {}}}
    with pytest.raises(AccessDenied):
        await Services.authorize_xai(services, 'jwt')


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [{}, {'sub': 'wrong'}, {'authorization_details': []},
                                    {'authorization_details': XAI_RAR[:1]}])
async def test_xai_requests_and_validates_exact_signed_rar(monkeypatch, changed):
    from urllib.parse import parse_qs
    services, _ = service_and_session()
    services.config['xai'] = {'client_id': 'xai-client', 'client_secret': 'test-only'}
    claims = {'sub': 'xai-client', 'authorization_details': XAI_RAR, **changed}
    services.identity = SimpleNamespace(validate=lambda *args: claims)
    def handler(request):
        form = parse_qs(request.content.decode())
        assert json.loads(form['authorization_details'][0]) == XAI_RAR
        assert form['grant_type'] == ['client_credentials']
        return httpx.Response(200, json={'access_token': 'test-jwt'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    if changed:
        with pytest.raises(AccessDenied, match='RAR'):
            await services.client_token('xai')
    else:
        assert await services.client_token('xai') == 'test-jwt'


@pytest.mark.asyncio
async def test_failed_rotation_does_not_reuse_expired_key():
    services, session = service_and_session()
    from app.services import ModelCredential
    services._xai_credential = ModelCredential('expired-canary', 'xai/creds/lumen/old', 'old', time.monotonic() - 1, 300, False)
    async def token(_): raise AccessDenied('Verify unavailable')
    services.client_token = token
    with pytest.raises(AccessDenied, match='Verify unavailable'):
        await services.model_credentials(session)


@pytest.mark.asyncio
@pytest.mark.parametrize('ttl,lease', [(20, 'xai/creds/lumen/key'), (0, 'xai/creds/lumen/key'),
                                        (300, ''), (300, 'other/creds/key')])
async def test_unusable_lease_rejected(ttl, lease):
    services, session = service_and_session()
    async def token(_): return 'jwt'
    async def read(*args, **kwargs):
        return {'data': {'api_key': 'canary'}, 'lease_duration': ttl, 'lease_id': lease}
    services.client_token, services.vault_get = token, read
    with pytest.raises(AccessDenied):
        await services.model_credentials(session)


@pytest.mark.asyncio
async def test_denied_dynamic_key_never_falls_back_to_static_key():
    services, session = service_and_session()
    services.config['model']['api_key'] = 'old-static-key'
    async def token(_): return 'jwt'
    async def denied(*args, **kwargs): raise VaultPermissionDenied('denied')
    services.client_token, services.vault_get = token, denied
    with pytest.raises(VaultPermissionDenied):
        await services.model_credentials(session)


@pytest.mark.asyncio
async def test_expired_login_does_not_mint_keys():
    services, session = service_and_session()
    session.expires_at = 0
    with pytest.raises(AccessDenied):
        await services.model_credentials(session)


def test_bootstrap_reads_oauth_client_and_never_static_xai_key(monkeypatch):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/task-agents'):
            return httpx.Response(404)
        if request.url.path.endswith('/model'):
            data = {'provider': 'xai', 'api_key': 'obsolete', 'credential_source': 'vault_dynamic'}
        else:
            data = {'client_id': 'client', 'client_secret': 'test-only'}
        return httpx.Response(200, json={'data': {'data': data}})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv('CHATBOT_BOOTSTRAP_TOKEN', 'test-bootstrap')
    import app.security as security
    monkeypatch.setattr(security.ssl, 'create_default_context', lambda **kwargs: None)
    config = load_config()
    assert '/v1/secrets/data/chatbot/xai' in paths
    assert '/v1/secrets/data/xai' not in paths
    assert '/v1/secrets/data/xai_mgmt' not in paths
    assert paths[-1] == '/v1/auth/token/revoke-self'
    assert 'api_key' not in config['model']


@pytest.mark.asyncio
async def test_agent_run_stops_before_lease_deadline(monkeypatch):
    from app import agent
    services, session = service_and_session()
    model = {**services.config['model'], 'api_key': 'canary'}
    async def credentials(_): return model, time.monotonic() + 0.03
    services.model_credentials = credentials
    cancelled = []
    async def invoke(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(agent, 'make_agent', lambda *args: SimpleNamespace(ainvoke=invoke))
    monkeypatch.setattr(agent, 'make_model', lambda *args: object())
    from app.guardrails import ScopeDecision
    monkeypatch.setattr(agent, 'assess_request', AsyncMock(return_value=ScopeDecision(category='conversation')))
    with pytest.raises(AccessDenied, match='tiempo permitido'):
        await agent.reply(services, session, 'hello')
    assert cancelled == [True]
    assert 'api_key' not in model
