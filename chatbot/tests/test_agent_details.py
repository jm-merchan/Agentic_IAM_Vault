"""Identity attribution, live metadata, UI links, and credential boundaries."""
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest

from app.agent_details import AgentInspector, agent_markdown, token_agent, vault_ui_url
from app.i18n import Translator
from app.trace_flow import build_flow
from test_trace_flow import record


@pytest.mark.asyncio
async def test_live_metadata_projects_only_public_fields_and_links(monkeypatch):
    calls = []
    registration = dict(id='registry-id', entity_id='entity-id', display_name='chatbot-task-read',
                        ceiling_policies=['chatbot-task-read'], no_default_ceiling_policy=True,
                        optional_authorization_details=False, description='Demo agent', owner='',
                        creation_time='2026-10-20', last_updated_time='2026-10-21')
    entity = dict(id='entity-id', name='chatbot-task-read', disabled=False, policies=[],
                  mfa_secrets={'secret': 'CANARY_MFA'}, metadata={'secret': 'CANARY_METADATA'},
                  aliases=[dict(name='chatbot-task-read', id='alias-id', canonical_id='entity-id',
                                mount_accessor='oauth-resource-server_ns_profile-id')])
    def handler(request):
        calls.append(request)
        assert request.headers['x-vault-token'] == 'CANARY_INSPECTOR_TOKEN'
        assert request.headers['x-vault-namespace'] == 'verify'
        assert request.method == 'GET'
        if 'registration' in request.url.path:
            data = registration
        elif 'identity/entity' in request.url.path:
            data = entity
        elif 'oauth-resource-server' in request.url.path:
            data = {'config_id': 'profile-id', 'issuer_id': 'https://verify.test/oauth2', 'secret': 'CANARY_CONFIG'}
        else:
            data = {'policy': 'path "database/creds/chatbot-readonly" { capabilities = ["read"] }'}
        return httpx.Response(200, json={'data': data})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    inspector = AgentInspector({'vault_addr': 'https://vault.test'}, True, token='CANARY_INSPECTOR_TOKEN')
    detail = await inspector.describe('chatbot-task-read')
    assert detail['available'] and detail['entity_id'] == 'entity-id'
    assert ['Issuer', 'https://verify.test/oauth2'] in detail['aliases'][0]['fields']
    assert detail['policies'][0]['levels'] == ['Techo OBO']
    assert len(calls) == 4
    for item in (detail['entity_url'], detail['registry_url'], detail['aliases'][0]['url'], detail['policies'][0]['url']):
        assert parse_qs(urlsplit(item).query) == {'namespace': ['verify']}
        assert item.startswith('https://vault.test/ui/vault/')
    report = agent_markdown(detail, Translator('en'))
    assert 'Vault agent' in report and 'OBO ceiling' in report and 'no direct policies' in report
    assert 'CANARY' not in json.dumps(detail) + report


@pytest.mark.asyncio
async def test_inspection_failure_is_explicit_and_does_not_fabricate_entity(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(
        lambda req: httpx.Response(403, json={'errors': ['CANARY_SECRET']}))))
    inspector = AgentInspector({'vault_addr': 'https://vault.test'}, True, token='synthetic')
    detail = await inspector.describe('chatbot-task-read')
    assert not detail['available'] and 'entity_url' not in detail
    assert 'CANARY_SECRET' not in json.dumps(detail)
    assert await inspector.describe('../verify-admin') is None


def test_token_attribution_uses_obo_actor_or_autonomous_subject():
    config = {'task-read': {'client_id': 'task'}, 'xai': {'client_id': 'model'}}
    encode = lambda claims: jwt.encode(claims, 'synthetic-key-with-32-characters-minimum', algorithm='HS256')
    assert token_agent(encode({'sub': 'human', 'actor-token': {'sub': 'task'}}), config) == 'chatbot-task-read'
    assert token_agent(encode({'sub': 'model'}), config) == 'chatbot-xai'
    assert token_agent(encode({'sub': 'unknown'}), config) == ''
    assert token_agent('opaque-token', config) == ''


def test_trace_never_confuses_business_actor_and_provider_or_search_agent():
    records = [record('lumen.action', 'root', 0, 100, **{'agent.identity': 'chatbot-task-read'})]
    for n, attrs in [
        ('verify.client_credentials', {'agent.identity': 'chatbot-xai'}),
        ('vault.read', {'agent.identity': 'chatbot-xai', 'vault.path': 'xai/creds/lumen'}),
        ('xai.chat', {}), ('anthropic.chat', {}), ('openai.token_exchange', {}),
        ('tavily.search', {}), ('mysql.query', {'agent.identity': 'chatbot-task-read'}),
        ('vault.jwks', {}),
    ]:
        records.append(record(n, str(len(records)), len(records), len(records)+1, 'root', **attrs))
    calls = build_flow(records)['calls']
    assert [c['agent_name'] for c in calls] == ['chatbot-xai', 'chatbot-xai', 'chatbot-xai',
        'chatbot-anthropic', 'chatbot-openai', 'chatbot-research', 'chatbot-task-read', '']


@pytest.mark.parametrize('base', ['javascript:alert(1)', 'https://token@vault.test', '//vault.test'])
def test_links_cannot_contain_credentials_or_non_http_schemes(base):
    with pytest.raises(ValueError):
        vault_ui_url(base, 'agents/registry')


def test_policy_names_are_encoded_as_path_components():
    from urllib.parse import quote
    url = vault_ui_url('https://vault.test', 'policy/acl/' + quote('policy/?injected=1', safe=''))
    assert parse_qs(urlsplit(url).query) == {'namespace': ['verify']}
    assert 'policy%2F%3Finjected%3D1' in url
