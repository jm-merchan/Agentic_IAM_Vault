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
    def response(pair, label, token, **kwargs):
        if kwargs.get('revoke'):
            status, body = 200, {}
        else:
            status = 403 if pair.blocked and label == 'A' else 200
            body = {'data': {'username': 'private-sql-user', 'password': 'private-sql-password'}, 'lease_duration': 120}
        pair.rows.append(dict(phase=kwargs['phase'], token=label, status=status, trace_id='a'*32))
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
    await manager.block(session, mode)
    manager._sql_accepts.return_value = False
    result = await manager.check(session, mode)
    assert result['verified']
    assert [r['status'] for r in result['rows']] == [200, 200, 200, 403, 200]
    assert manager.services.exchange.await_count == (2 if mode == 'delegated' else 0)
    assert manager._direct.await_count == (2 if mode == 'direct' else 0)
    assert result['sql_result'] == ('revoked' if mode == 'delegated' else '')
    public = str(result)
    for secret in ('private-operator', 'private-sql-password', 'private-sql-user', 'access_token'):
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
    assert not pair.tokens and not pair.sql


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
    labels = (['1. Crear tokens y comprobar acceso', '2. Bloquear token A', '3. Repetir acceso con A y B']
              if language == 'es' else ['1. Create tokens and check access', '2. Block token A', '3. Retry access with A and B'])
    async with user_simulation(page) as user:
        await user.open('/')
        for index, label in enumerate(labels):
            await user.should_see(label)
            if index == 2: manager._sql_accepts.return_value = False
            user.find(label, kind=ui.button).click()
            await asyncio.sleep(.1)
        assert manager.view(session, 'delegated')['verified']
        assert manager.services.exchange.await_count == 2
        await user.should_see('Demostrado:' if language == 'es' else 'Proven:')

