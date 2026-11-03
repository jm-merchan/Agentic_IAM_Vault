import asyncio
from copy import deepcopy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nicegui import ui
from nicegui.testing.user_simulation import user_simulation

from app.oauth_revocation_lab import OAuthRevocationLab, PATHS, payload_for
from app.oauth_revocation_ui import render_oauth_revocation
from app.rar import authorization_details
from app.security import AccessDenied, ISSUER, Session


def setup(mode='delegated'):
    session = Session('owner', subject='human', groups=['writers'], expires_at=time.time()+600)
    config = {'oidc': {'client_id': 'actor'}, 'xai': {'client_id': 'direct'}, 'vault_addr': 'https://vault'}
    claims = {}
    for label in ('A', 'B'):
        claims[label] = {'iss': ISSUER, 'sub': 'human' if mode == 'delegated' else 'direct',
                         'jti': label, 'exp': time.time()+600,
                         'authorization_details': authorization_details(PATHS[mode], ['read'])}
        if mode == 'delegated':
            claims[label]['actor-token'] = {'sub': 'actor'}
    services = SimpleNamespace(config=config, vault_tls=True,
        identity=SimpleNamespace(validate=lambda token, _: deepcopy(claims[token]), sessions={'owner': session}),
        role=lambda s: s.require_login(), exchange=AsyncMock(side_effect=['A', 'B']))
    manager = OAuthRevocationLab(services, token='private-operator')
    manager._direct = AsyncMock(side_effect=['A', 'B'])
    manager._sql_accepts = AsyncMock(return_value=True)
    async def system(pair, index, phase):
        accepted = not (pair.blocked and index == 0)
        setattr(pair.credentials[index], 'before' if phase == 'system_before' else 'after',
                'accepted' if accepted else 'rejected')
        return accepted
    async def lookup(pair, index, phase):
        state = 'missing' if pair.blocked and index == 0 else 'active'
        pair.credentials[index].state = state
        return state
    manager._system = AsyncMock(side_effect=system)
    manager._lookup = AsyncMock(side_effect=lookup)
    def response(pair, label, token, **kwargs):
        if kwargs.get('revoke'):
            status, body = 200, {}
        else:
            status = 403 if pair.blocked and label == 'A' else 200
            body = {'data': {'username': 'private-sql-user', 'password': 'private-sql-password', 'api_key': 'private-api-key'},
                    'lease_duration': 120, 'lease_id': PATHS[pair.mode] + '/' + label}
        pair.rows.append(dict(phase=kwargs['phase'], token=label, target='Vault', status=status, trace_id='a'*32))
        return status, body
    manager._request = AsyncMock(side_effect=response)
    services.oauth_revocation = manager
    return manager, session, claims


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['delegated', 'direct'])
async def test_same_pair_is_reused_and_control_remains_live(mode):
    manager, session, _ = setup(mode)
    before = await manager.prepare(session, mode)
    assert [r['status'] for r in before['rows']] == [200, 200]
    await manager.access(session, mode)
    await manager.block(session, mode)
    result = await manager.check(session, mode)
    assert result['verified']
    assert [r['status'] for r in result['rows']] == [200, 200, 200, 403, 200]
    assert manager.services.exchange.await_count == (2 if mode == 'delegated' else 0)
    assert manager._direct.await_count == (2 if mode == 'direct' else 0)
    assert result['token_verified'] and result['lease_verified'] and result['system_verified']
    assert result['leases'][0]['state'] == 'missing'
    assert result['leases'][1]['after'] == 'accepted'
    public = str(result)
    for secret in ('private-operator', 'private-sql-password', 'private-sql-user', 'private-api-key', 'access_token'):
        assert secret not in public
    await manager.clear(session, mode)
    assert manager.view(session, mode) is None
    assert manager._request.call_args.kwargs['revoke']['unique_id'] == 'B'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['sid', 'subject', 'task_agent', 'expired'])
async def test_another_session_identity_or_agent_cannot_revoke(change):
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    if change == 'expired':
        session.expires_at = 0
    else:
        setattr(session, change, 'different')
    count = manager._request.await_count
    with pytest.raises(AccessDenied):
        await manager.block(session, 'delegated')
    assert manager._request.await_count == count


@pytest.mark.asyncio
async def test_expiry_cannot_be_reported_as_successful_revocation():
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    pair = manager._pairs[(session.sid, 'delegated')]
    pair.claims[0]['exp'] = time.time()+20
    with pytest.raises(AccessDenied, match='30 segundos'):
        await manager.block(session, 'delegated')
    assert not pair.blocked


@pytest.mark.asyncio
async def test_failed_operator_response_does_not_mark_token_blocked():
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    await manager.access(session, 'delegated')
    manager._request = AsyncMock(return_value=(403, {}))
    with pytest.raises(AccessDenied, match='no ha aceptado'):
        await manager.block(session, 'delegated')
    assert not manager.view(session, 'delegated')['blocked']


@pytest.mark.asyncio
@pytest.mark.parametrize('tamper', ['subject', 'actor', 'rar', 'same_jti'])
async def test_issued_pair_must_match_identity_actor_rar_and_distinct_jti(tamper):
    manager, session, claims = setup()
    if tamper == 'subject': claims['B']['sub'] = 'other'
    if tamper == 'actor': claims['B']['actor-token']['sub'] = 'other'
    if tamper == 'rar': claims['B']['authorization_details'] = []
    if tamper == 'same_jti': claims['B']['jti'] = 'A'
    with pytest.raises(AccessDenied):
        await manager.prepare(session, 'delegated')
    assert manager.view(session, 'delegated') is None
    assert all(call.kwargs.get('revoke') for call in manager._request.call_args_list)


@pytest.mark.asyncio
async def test_abandoned_pair_cleanup_does_not_revoke_login_token():
    manager, session, _ = setup()
    session.access_token = 'private-human-login'
    await manager.prepare(session, 'delegated')
    pair = manager._pairs[(session.sid, 'delegated')]
    await manager._clean(pair)
    targets = [c.kwargs['revoke']['unique_id'] for c in manager._request.call_args_list if c.kwargs.get('revoke')]
    assert targets == ['A', 'B']
    assert not pair.tokens and all(not c.secret for c in pair.credentials)


@pytest.mark.asyncio
async def test_operator_http_headers_remain_server_side(monkeypatch):
    manager, _, _ = setup()
    factory = httpx.AsyncClient
    def respond(request):
        assert request.headers['X-Vault-Token'] == 'private-operator'
        assert request.headers['X-Vault-Namespace'] == 'verify'
        return httpx.Response(204)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(respond)))
    async with manager._client() as client:
        response = await client.post('/v1/auth/token/renew-self', json={})
    assert response.status_code == 204


def test_api_exp_is_remaining_duration():
    assert payload_for({'iss': ISSUER, 'jti': 'A', 'exp': 1600}, now=1000)['exp'] == 615


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['es', 'en'])
async def test_ui_buttons_drive_real_manager_without_reissuing_tokens(language):
    manager, session, _ = setup()
    async def run_action(name, action): return await action()
    async def page():
        await render_oauth_revocation(manager.services, session, lambda: None, run_action, language)
    labels = (['1. Crear tokens y leases', '2. Probar acceso al sistema final', '3. Revocar token A', '4. Verificar token, lease y acceso']
              if language == 'es' else ['1. Create tokens and leases', '2. Test final system access', '3. Revoke token A', '4. Verify token, lease and access'])
    async with user_simulation(page) as user:
        await user.open('/')
        for index, label in enumerate(labels):
            await user.should_see(label)
            user.find(label, kind=ui.button).click()
            await asyncio.sleep(.1)
        assert manager.view(session, 'delegated')['verified']
        assert manager.services.exchange.await_count == 2
        await user.should_see('Demostrado:' if language == 'es' else 'Proven:')


@pytest.mark.asyncio
async def test_block_requires_successful_backend_access_and_live_leases():
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    with pytest.raises(AccessDenied, match='sistema final'):
        await manager.block(session, 'delegated')
    await manager.access(session, 'delegated')
    manager._pairs[(session.sid, 'delegated')].credentials[0].deadline = time.monotonic() + 10
    with pytest.raises(AccessDenied, match='15 segundos'):
        await manager.block(session, 'delegated')


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['expired', 'lookup_unknown', 'a_accepted', 'b_rejected', 'network'])
async def test_jwt_block_alone_never_proves_lease_and_backend_revocation(failure, monkeypatch):
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    await manager.access(session, 'delegated')
    await manager.block(session, 'delegated')
    pair = manager._pairs[(session.sid, 'delegated')]
    if failure == 'expired': pair.credentials[0].deadline = time.monotonic() - 1
    if failure == 'lookup_unknown': manager._lookup = AsyncMock(side_effect=['unknown'] * 8 + ['active'])
    if failure == 'a_accepted': manager._system = AsyncMock(return_value=True)
    if failure == 'b_rejected': manager._system = AsyncMock(side_effect=[False, False])
    if failure == 'network': manager._system = AsyncMock(return_value=None)
    monkeypatch.setattr('app.oauth_revocation_lab.asyncio.sleep', AsyncMock())
    result = await manager.check(session, 'delegated')
    assert result['token_verified'] and not result['verified']


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body,state', [(200, {'data': {'id': PATHS['delegated']+'/A', 'ttl': 100}}, 'active'),
    (400, {'errors': ['invalid lease']}, 'missing'), (404, {'errors': ['lease not found']}, 'missing'),
    (403, {'errors': ['permission denied']}, 'unknown'), (500, {'errors': ['invalid lease']}, 'unknown'),
    (400, {'errors': ['unrelated error']}, 'unknown')])
async def test_lease_lookup_does_not_confuse_failure_with_absence(code, body, state, monkeypatch):
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    factory = httpx.AsyncClient
    def respond(request):
        assert request.headers['X-Vault-Token'] == 'private-operator'
        assert request.url.path == '/v1/sys/leases/lookup'
        return httpx.Response(code, json=body)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(respond)))
    pair = manager._pairs[(session.sid, 'delegated')]
    assert await OAuthRevocationLab._lookup(manager, pair, 0, 'lease_after') == state


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body,expected', [(200, {}, True), (401, {}, False), (403, {}, False),
    (400, {'error': 'Invalid API key'}, False), (400, {'error': 'Invalid request'}, None), (429, {}, None), (500, {}, None)])
async def test_xai_probe_requires_explicit_authentication_result(code, body, expected, monkeypatch):
    manager, session, _ = setup('direct')
    await manager.prepare(session, 'direct')
    factory = httpx.AsyncClient
    def respond(request):
        assert str(request.url) == 'https://api.x.ai/v1/api-key'
        assert request.headers['Authorization'] == 'Bearer private-api-key'
        return httpx.Response(code, json=body)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(respond)))
    pair = manager._pairs[(session.sid, 'direct')]
    assert await OAuthRevocationLab._system(manager, pair, 0, 'system_before') is expected
    assert 'private-api-key' not in str(pair.public())


@pytest.mark.asyncio
async def test_lookup_latency_and_ttl_rounding_cannot_extend_revocation_proof_window(monkeypatch):
    manager, session, _ = setup()
    await manager.prepare(session, 'delegated')
    pair = manager._pairs[(session.sid, 'delegated')]
    pair.credentials[0].deadline, pair.credentials[0].expires_at = 500, 2000
    clock = {'mono': 50, 'wall': 1000}
    monkeypatch.setattr('app.oauth_revocation_lab.time', SimpleNamespace(
        monotonic=lambda: clock['mono'], time=lambda: clock['wall']))
    factory = httpx.AsyncClient
    def respond(request):
        clock.update(mono=70, wall=1020)
        return httpx.Response(200, json={'data': {'id': pair.credentials[0].lease_id, 'ttl': 100}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(respond)))
    assert await OAuthRevocationLab._lookup(manager, pair, 0, 'lease_before') == 'active'
    assert pair.credentials[0].deadline == 149
    assert pair.credentials[0].expires_at == 1099

