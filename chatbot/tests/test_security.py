import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security import AccessDenied, Identity, ISSUER, Session, role_for_groups
from app.services import Services

GROUPS = {'readonly': ['reader-id', 'chatbot-readers'], 'readwrite': ['writer-id', 'chatbot-writers']}


def test_unknown_group_never_grants_database_access():
    assert role_for_groups(['administrator', 'readwrite', 'writer-id-suffix'], GROUPS) is None
    assert role_for_groups([], GROUPS) is None


def test_exact_group_membership_selects_role():
    assert role_for_groups(['reader-id'], GROUPS) == 'readonly'
    assert role_for_groups(['writer-id'], GROUPS) == 'readwrite'


def test_expired_session_denied_before_request():
    with pytest.raises(AccessDenied):
        Session('s', subject='u', expires_at=time.time() - 1).require_login()


def test_readonly_cannot_prepare_write_even_if_tool_is_called_directly():
    services = object.__new__(Services)
    services.config = {'runtime': {'groups': GROUPS}}
    reader = Session('s', subject='u', groups=['reader-id'], expires_at=time.time() + 60)
    with pytest.raises(AccessDenied):
        services.prepare_request(reader, 1, 'attempt to bypass UI')
    assert reader.pending is None


@pytest.mark.asyncio
async def test_invalid_state_fails_before_network():
    identity = Identity({'oidc': {'client_id': 'client'}})
    session, url = identity.start()
    assert 'code_challenge_method=S256' in url
    with pytest.raises(AccessDenied):
        await identity.finish(session.sid, 'forged-state', 'fake-code')


def test_jwt_requires_signature_issuer_audience_and_expiry():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity = Identity({})
    identity.keys = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))
    claims = dict(iss=ISSUER, sub='u', aud='client', iat=int(time.time()), exp=int(time.time()) + 60)
    assert identity.validate(jwt.encode(claims, key, algorithm='RS256'), 'client')['sub'] == 'u'
    for changed, signing_key in [(claims, other), ({**claims, 'iss': 'https://attacker.invalid'}, key),
                                 ({**claims, 'aud': 'other-client'}, key), ({**claims, 'exp': 1}, key)]:
        with pytest.raises(jwt.PyJWTError):
            identity.validate(jwt.encode(changed, signing_key, algorithm='RS256'), 'client')


@pytest.mark.asyncio
async def test_confirmation_is_single_use_and_expires():
    services = object.__new__(Services)
    session = Session('s', subject='u', expires_at=time.time() + 60)
    session.pending = dict(plan_id=1, note='demo', created_at=time.time() - 301)
    with pytest.raises(AccessDenied):
        await services.confirm_request(session)
    assert session.pending is None

@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [
    {'sub': 'other-user'}, {'actor-token': {'sub': 'other-agent'}},
    {'authorization_details': [{'type': 'vault:path_access', 'path': '*', 'capabilities': ['read']}]},
])
async def test_exchange_rejects_wrong_subject_actor_or_rar(monkeypatch, changed):
    import httpx
    services = object.__new__(Services)
    services.config = {'oidc': {'client_id': 'actor'}, 'sts': {'client_id': 'sts', 'client_secret': 'test-only'}}
    path = 'database/creds/chatbot-readonly'
    claims = {'sub': 'user', 'actor-token': {'sub': 'actor'},
              'authorization_details': [{'type': 'vault:path_access', 'path': path, 'capabilities': ['read']}]}
    services.identity = SimpleNamespace(validate=lambda *args: {**claims, **changed})
    async def actor_token(_): return 'fake-actor-token'
    services.client_token = actor_token
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return httpx.Response(200, json={'access_token': 'fake-exchanged-token'},
                                  request=httpx.Request('POST', args[0]))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: Client())
    session = Session('s', subject='user', access_token='fake-human-token', expires_at=time.time()+60)
    with pytest.raises(AccessDenied):
        await services.exchange(session, path)


@pytest.mark.asyncio
async def test_private_search_text_is_rejected_before_egress():
    services = object.__new__(Services)
    session = Session('s', subject='u', expires_at=time.time()+60)
    with pytest.raises(AccessDenied):
        await services.search(session, 'private database row: customer@example.invalid')


@pytest.mark.asyncio
@pytest.mark.parametrize('write,path', [(False, 'database/creds/chatbot-readonly'),
                                       (True, 'database/creds/chatbot-readwrite')])
async def test_writer_reads_use_ro_credentials_and_vault_denial_stops_sql(write, path):
    from unittest.mock import AsyncMock
    from app.services import VaultPermissionDenied
    services = object.__new__(Services)
    services.role = lambda session: 'readwrite'
    services.exchange = AsyncMock(return_value='rar-jwt')
    services.vault_get = AsyncMock(side_effect=VaultPermissionDenied('blocked'))
    session = object()
    with pytest.raises(VaultPermissionDenied):
        await services.database(session, 'UNREACHABLE SQL', write=write)
    services.exchange.assert_awaited_once_with(session, path)
    services.vault_get.assert_awaited_once_with(path, 'rar-jwt')


@pytest.mark.asyncio
async def test_deep_agent_only_exposes_business_tools_and_rejects_shell(monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_xai import ChatXAI
    from app.agent import make_agent
    calls = []
    async def generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            message = AIMessage(content='', tool_calls=[{'name': 'execute', 'args': {'command': 'echo forbidden'}, 'id': 'attempt'}])
        else:
            denied = [m for m in messages if isinstance(m, ToolMessage)]
            assert any(m.status == 'error' and 'not available' in m.content for m in denied)
            message = AIMessage(content='Rejected forbidden tool')
        return ChatResult(generations=[ChatGeneration(message=message)])
    monkeypatch.setattr(ChatXAI, '_agenerate', generate)
    services = SimpleNamespace(config={'model': {'provider': 'xai', 'model': 'grok-4.3', 'api_key': 'test-only'}},
                               role=lambda session: 'readonly')
    session = Session('s', subject='u', expires_at=time.time()+60)
    graph = make_agent(services, session)
    result = await graph.ainvoke({'messages': [{'role': 'user', 'content': 'test'}]}, config={'recursion_limit': 10})
    names = {t['function']['name'] for t in calls[0]['tools']}
    assert names == {'consultar_planes', 'consultar_solicitudes', 'consultar_inventario', 'buscar_en_web'}
    assert result['messages'][-1].content == 'Rejected forbidden tool'
