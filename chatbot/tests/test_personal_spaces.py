import importlib.util
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.personal_spaces import access, secret_path
from app.rar import LAB_CONTEXT
from app.security import AccessDenied, Session
from app.services import VaultPermissionDenied, VaultResponseError
from app.telemetry import records_for, span, trace_id
from app.trace_flow import build_flow, _personal_context

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {'personal-spaces': {'version': 1, 'prefix': 'lumen-personal', 'users': [
        {'subject': 'alice', 'entity_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'name': 'Alice'},
        {'subject': 'bob', 'entity_id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'name': 'Bob'}]}}


def session(mode='legacy'):
    return Session('session', subject='alice', expires_at=time.time()+300, task_agent=mode)


@pytest.mark.parametrize('name', ['../bob/demo', 'a/b', 'a%2fb', '*', '', 'a?list=true', 'a'*65])
def test_names_cannot_escape_personal_prefix(name):
    with pytest.raises(AccessDenied):
        secret_path(config(), 'alice', name)


@pytest.mark.asyncio
async def test_cross_owner_probe_reaches_vault_with_explicit_target_rar():
    service = SimpleNamespace(config=config(), event=lambda *a: None,
        exchange=AsyncMock(return_value='synthetic'), vault_get=AsyncMock(side_effect=VaultPermissionDenied('denied')))
    s = session()
    result = await access(service, s, 'read', target='bob')
    path = secret_path(config(), 'bob')
    service.exchange.assert_awaited_once_with(s, path, ['read'])
    service.vault_get.assert_awaited_once_with(path, 'synthetic', params=None)
    assert result['status'] == 403 and result['expected'] is False
    assert LAB_CONTEXT.get() == {}


@pytest.mark.asyncio
async def test_ceiling_denial_is_real_and_writes_use_cas():
    service = SimpleNamespace(config=config(), event=lambda *a: None,
        exchange=AsyncMock(return_value='synthetic'), vault_post=AsyncMock(side_effect=VaultPermissionDenied('denied')))
    result = await access(service, session('read'), 'write', value={'note': 'synthetic'}, version=4)
    assert result['expected'] is False and result['status'] == 403
    assert service.vault_post.await_args.args[-1] == {'data': {'note': 'synthetic'}, 'options': {'cas': 4}}


@pytest.mark.asyncio
async def test_not_found_and_server_errors_are_not_reported_as_denials():
    service = SimpleNamespace(config=config(), event=lambda *a: None, exchange=AsyncMock(return_value='synthetic'))
    for status in (400, 404, 500):
        service.vault_get = AsyncMock(side_effect=VaultResponseError(status))
        result = await access(service, session(), 'read', target='bob')
        assert result['status'] == status


@pytest.mark.asyncio
async def test_trace_exposes_ownership_but_no_secret_data():
    service = SimpleNamespace(config=config(), event=lambda *a: None, exchange=AsyncMock(return_value='synthetic'))
    service.config['oidc'] = {'client_id': 'agent-client', 'client_secret': 'PRIVATE-CLIENT-SECRET'}
    service.config['personal-spaces']['policies'] = {'user': (ROOT/'policies/personal-user.hcl').read_text()}
    async def get(path, token, **kwargs):
        with span('vault.read', **{'vault.path': path, 'http.response.status_code': 200}):
            return {'data': {'data': {'note': 'PRIVATE-VALUE'}, 'metadata': {'version': 1}}}
    service.vault_get = get
    with span('lumen.personal.read'):
        tid = trace_id()
        await access(service, session(), 'read')
    flow = build_flow(records_for({tid}))
    personal = flow['calls'][0]['personal']
    assert personal['owner_entity'] == config()['personal-spaces']['users'][0]['entity_id']
    assert personal['subject'] == 'alice' and personal['actor_client_id'] == 'agent-client'
    assert '{{identity.entity.id}}' in personal['user_policy_snapshot']
    assert personal['path_matches_owner'] is True
    assert 'PRIVATE-VALUE' not in str(flow) and 'PRIVATE-CLIENT-SECRET' not in str(flow)


@pytest.mark.parametrize('listing', [False, True])
def test_explanation_expands_human_policy_independently_of_requested_owner(listing):
    owner = config()['personal-spaces']['users'][0]['entity_id']
    target = config()['personal-spaces']['users'][1]['entity_id']
    path = secret_path(config(), 'bob', listing=listing)
    data = _personal_context({'personal.path': path, 'personal.owner_entity': owner,
                              'personal.target_entity': target})
    assert owner in data['expanded_path'] and target not in data['expanded_path']
    assert data['path_matches_owner'] is False and data['path'] == path
    assert '{{identity.entity.id}}' in data['template_path']
    # An old trace must not invent a Verify subject or issuer from a UUID.
    assert 'subject' not in data and 'issuer' not in data


def test_explanation_only_projects_recorded_rar_identity_fields():
    import json
    path = secret_path(config(), 'alice')
    entry = {'type': 'vault:path_access', 'path': path, 'capabilities': ['read'],
             'allowed_parameters': {'password': ['PRIVATE-PARAMETER']}}
    data = _personal_context({'personal.path': path, 'auth.rar.presented': json.dumps([entry]),
                              'personal.client_secret': 'PRIVATE-CLIENT',
                              'vault.auth.jwt': 'PRIVATE-JWT'})
    assert data['rar_source'] == 'presented'
    assert data['authorization_details'] == [{k: entry[k] for k in ('type', 'path', 'capabilities')}]
    assert 'PRIVATE' not in str(data) and 'path_matches_owner' not in data


def test_explanation_handles_missing_or_malformed_rar_without_fabricating_it():
    for value in ('not-json', '{}', 'null', '[null]', '[]'):
        result = _personal_context({'personal.path': secret_path(config(), 'alice'),
                                    'auth.rar.presented': value})
        assert 'authorization_details' not in result


def test_installer_preserves_existing_secrets_and_ceiling_policies():
    spec = importlib.util.spec_from_file_location('configure_personal', ROOT/'scripts/configure-personal-spaces.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    writes = []
    def respond(request):
        path = request.url.path.removeprefix('/v1/')
        if request.method != 'GET':
            import json
            writes.append((path, json.loads(request.content)))
            return httpx.Response(204)
        data = {}
        if path == 'sys/mounts':
            data = {'secrets/': {'type': 'kv', 'options': {'version': '2'}}}
        elif path == 'secrets/data/chatbot/directory':
            data = {'data': {'users': [{'username': 'lumen-'+r, 'user_id': r} for r in ('reader','writer','supervisor')]}}
        elif path.startswith('identity/entity/name/'):
            data = {'id': path.split('-')[-1], 'disabled': False}
        elif path.startswith('agent-registry/'):
            data = {'display_name': path.split('/')[-1], 'entity_id': 'agent',
                    'ceiling_policies': ['existing-ceiling', 'existing-deny'],
                    'optional_authorization_details': False, 'no_default_ceiling_policy': True}
        elif path.startswith('secrets/metadata/'):
            data = {'current_version': 7}
        return httpx.Response(200, json={'data': data})
    with httpx.Client(base_url='https://vault.test', transport=httpx.MockTransport(respond)) as client:
        module.configure(client)
        module.configure(client)
    assert not any(path.startswith('secrets/data/lumen-personal/') for path, _ in writes)
    for path, body in writes:
        if path == 'agent-registry/register':
            assert body['ceiling_policies'][:2] == ['existing-ceiling', 'existing-deny']
            assert body['optional_authorization_details'] is False
    assert '{{identity.entity.id}}' in module.POLICIES['user']
    assert 'secrets/data/chatbot/' not in module.POLICIES['user']
