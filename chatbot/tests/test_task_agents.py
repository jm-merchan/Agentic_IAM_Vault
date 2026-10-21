"""Task mode must select a distinct, login-bound actor without widening access."""
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.security import AccessDenied, Identity, Session
from app.services import Services
from app.task_agents import TASK_AGENTS, actor_credential, task_allows, task_agents_ready


def config():
    return {
        name: {'client_id': name + '-id', 'client_secret': 'synthetic-' + name}
        for name in ('oidc', 'sts', 'task-read', 'task-write', 'task-reveal')
    } | {'runtime': {'groups': {'readwrite': ['writers'], 'sensitive': ['supervisors']}}}


def session(mode='legacy', group='writers'):
    return Session('session', subject='human', groups=[group], expires_at=time.time() + 300,
                   access_token='synthetic-human-token', task_agent=mode)


@pytest.mark.parametrize('mode', ['legacy', *TASK_AGENTS])
def test_login_uses_selected_client_and_retains_pkce(mode):
    identity = Identity(config())
    pending, url = identity.start(mode)
    params = parse_qs(urlparse(url).query)
    assert pending.task_agent == mode
    assert params['client_id'] == [identity.config[actor_credential(identity.config, mode)]['client_id']]
    assert params['code_challenge_method'] == ['S256']
    assert pending.verifier not in url


def test_legacy_installation_remains_usable_without_extension():
    identity = Identity({'oidc': {'client_id': 'original'}})
    pending, url = identity.start()
    assert pending.task_agent == 'legacy' and 'client_id=original' in url
    assert not task_agents_ready(identity.config)
    with pytest.raises(AccessDenied):
        identity.start('read')
    assert list(identity.sessions) == [pending.sid]


@pytest.mark.parametrize('mode', ['admin', '../oidc', 'sts', '', 'openai'])
def test_unlisted_identity_never_becomes_an_actor(mode):
    identity = Identity(config())
    with pytest.raises(AccessDenied):
        identity.start(mode)
    assert identity.sessions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['legacy', *TASK_AGENTS])
async def test_callback_binds_subject_token_audience_and_may_act_to_selected_client(monkeypatch, mode):
    identity = Identity(config())
    pending, _ = identity.start(mode)
    credential = identity.config[actor_credential(identity.config, mode)]
    validated = []
    def validate(token, audience):
        validated.append(audience)
        return {'sub': 'human', 'exp': time.time() + 300, 'nonce': pending.nonce,
                'may_act': {'client_id': credential['client_id']}, 'groups': ['writers']}
    identity.validate = validate
    calls = []
    def handle(req):
        calls.append(req)
        assert parse_qs(req.content.decode())['code_verifier'] == [pending.verifier]
        return httpx.Response(200, json={'id_token': 'synthetic-id', 'access_token': 'synthetic-access'})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(handle)))
    authenticated = await identity.finish(pending.sid, pending.state, 'code')
    assert authenticated.task_agent == mode
    assert validated == [credential['client_id'], credential['client_id']]
    assert authenticated.sid != pending.sid and pending.sid not in identity.sessions
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_callback_rejects_token_authorizing_different_actor(monkeypatch):
    identity = Identity(config())
    pending, _ = identity.start('read')
    identity.validate = lambda *a: {'sub': 'human', 'exp': time.time() + 300, 'nonce': pending.nonce,
                                   'may_act': {'client_id': 'task-write-id'}, 'groups': ['writers']}
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'id_token': 'id', 'access_token': 'access'}))))
    with pytest.raises(AccessDenied, match='delegación'):
        await identity.finish(pending.sid, pending.state, 'code')
    assert not pending.state


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['legacy', *TASK_AGENTS])
async def test_obo_uses_login_bound_actor_and_preserves_user_and_exact_rar(monkeypatch, mode):
    services = object.__new__(Services)
    services.config = config()
    original = deepcopy(services.config)
    s = session(mode)
    name = actor_credential(services.config, mode)
    path = 'database/creds/chatbot-readwrite'
    # Asking for a disallowed path is still sent to Vault for enforcement;
    # choosing an actor by path here would silently escalate a read agent.
    services.client_token = AsyncMock(return_value='actor-' + name)
    expected_rar = [{'type': 'vault:path_access', 'path': path, 'capabilities': ['read']}]
    services.identity = SimpleNamespace(validate=lambda *a: {
        'sub': s.subject, 'actor-token': {'sub': services.config[name]['client_id']},
        'authorization_details': expected_rar,
    })
    def handle(req):
        data = parse_qs(req.content.decode())
        assert data['subject_token'] == [s.access_token]
        assert data['actor_token'] == ['actor-' + name]
        return httpx.Response(200, json={'access_token': 'obo'})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(handle)))
    assert await services.exchange(s, path) == 'obo'
    services.client_token.assert_awaited_once_with(name)
    assert services.config == original and s.task_agent == mode


@pytest.mark.parametrize('mode,write,reveal', [
    ('legacy', True, True), ('read', False, False), ('write', True, False), ('reveal', False, True),
    ('forged', False, False),
])
def test_task_rights_intersect_user_rights(mode, write, reveal):
    services = object.__new__(Services)
    services.config = config()
    writer, supervisor = session(mode), session(mode, 'supervisors')
    assert task_allows(writer, 'write') is write
    assert services.can_reveal(writer) is False
    assert services.can_reveal(supervisor) is reveal
    if write:
        assert services.prepare_request(writer, 1, 'synthetic')['status'] == 'awaiting_user_confirmation'
    else:
        with pytest.raises(AccessDenied):
            services.prepare_request(writer, 1, 'synthetic')
    with pytest.raises(AccessDenied):
        services.prepare_request(supervisor, 1, 'synthetic')
