from unittest.mock import AsyncMock

import pytest

from app.security import AccessDenied
from app.services import Services, VaultPermissionDenied


FIXTURE = {'version': 1, 'profile_plaintext': 'CANARY_BASE64',
           'profile_ciphertext': 'vault:v1:CANARY_CIPHERTEXT',
           'dni': {'value': 'CANARY_DNI', 'token': 'CANARY_DNI_TOKEN'},
           'iban': {'value': 'CANARY_IBAN', 'token': 'CANARY_IBAN_TOKEN'}}
PATHS = (
    'database/creds/chatbot-readonly', 'database/creds/chatbot-readwrite',
    'secrets/data/verify-admin', 'transit/encrypt/lumen-applications',
    'transit/decrypt/lumen-applications', 'transform/encode/lumen-dni',
    'transform/decode/lumen-dni', 'transform/encode/lumen-iban',
    'transform/decode/lumen-iban',
)


def make_service(role='readonly', reveal=False):
    service = object.__new__(Services)
    service.config = {'runtime': {'permission_probe': FIXTURE}}
    service.role = lambda session: role
    service.can_reveal = lambda session: reveal
    service.event = lambda *args, **kwargs: None
    service.exchange = AsyncMock(return_value='CANARY_JWT')
    allowed = {PATHS[0]}
    if role == 'readwrite':
        allowed.update([PATHS[1], PATHS[3], PATHS[5], PATHS[7]])
    if reveal:
        allowed.update([PATHS[4], PATHS[6], PATHS[8]])

    async def get(path, token):
        if path not in allowed:
            raise VaultPermissionDenied('Denied')
        return {'data': {'username': 'CANARY_USER', 'password': 'CANARY_PASSWORD'}, 'lease_duration': 120}

    async def post(path, token, payload):
        if path not in allowed:
            raise VaultPermissionDenied('Denied')
        if path.startswith('transit/encrypt/'):
            data = {'ciphertext': 'vault:v1:CANARY_NEW_CIPHERTEXT'}
        elif path.startswith('transit/decrypt/'):
            assert payload == {'ciphertext': FIXTURE['profile_ciphertext']}
            data = {'plaintext': FIXTURE['profile_plaintext']}
        elif path.startswith('transform/encode/'):
            data = {'encoded_value': 'CANARY_NEW_TOKEN'}
        else:
            field = path.rsplit('-', 1)[1]
            assert payload == {'value': FIXTURE[field]['token'], 'transformation': 'lumen-' + field}
            data = {'decoded_value': FIXTURE[field]['value']}
        return {'data': data}

    service.vault_get = AsyncMock(side_effect=get)
    service.vault_post = AsyncMock(side_effect=post)
    return service, allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('role,reveal', [('readonly', False), ('readwrite', False), ('readonly', True)])
async def test_nine_real_probes_follow_role_matrix_and_never_return_values(role, reveal):
    service, allowed = make_service(role, reveal)
    session = object()
    output = await service.permission_probe(session)
    assert '9 de 9' in output
    assert 'CANARY' not in output
    assert service.vault_get.await_count == 3
    assert service.vault_post.await_count == 6
    assert [c.args[1] for c in service.exchange.call_args_list] == list(PATHS)
    for call in service.exchange.call_args_list[3:]:
        assert call.args[2] == ['update']
    for path in PATHS:
        result = 'Permitido' if path in allowed else 'Denegado'
        assert f'`{path}` | {result} | {result}' in output


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['vault_get', 'vault_post'])
async def test_service_outage_is_not_reported_as_a_policy_denial(method):
    service, _ = make_service('readwrite')
    setattr(service, method, AsyncMock(side_effect=AccessDenied('Unavailable')))
    with pytest.raises(AccessDenied, match='Unavailable'):
        await service.permission_probe(object())


@pytest.mark.asyncio
async def test_unexpected_permission_is_visible_in_actual_and_expected_columns():
    service, _ = make_service()
    service.vault_get = AsyncMock(return_value={'data': {'password': 'CANARY_PASSWORD'}})
    output = await service.permission_probe(object())
    assert '7 de 9' in output
    assert '`secrets/data/verify-admin` | Permitido | Denegado' in output
    assert 'CANARY' not in output


@pytest.mark.asyncio
async def test_missing_fixtures_fail_before_issuing_any_credentials():
    service, _ = make_service()
    service.config = {'runtime': {}}
    with pytest.raises(AccessDenied, match='no está preparada'):
        await service.permission_probe(object())
    service.exchange.assert_not_called()


@pytest.mark.asyncio
async def test_successful_http_with_wrong_recovered_value_does_not_pass():
    service, _ = make_service('readonly', True)
    service.vault_post = AsyncMock(side_effect=[VaultPermissionDenied('Denied'),
                                               {'data': {'plaintext': 'WRONG_CANARY'}}])
    with pytest.raises(AccessDenied, match='resultado ficticio esperado'):
        await service.permission_probe(object())


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['en', 'es'])
@pytest.mark.parametrize('unexpected_access', [False, True])
async def test_probe_trace_reports_actual_decisions_independently_of_language(language, unexpected_access):
    from app.security import Session
    from app.telemetry import span, trace_id, records_for

    service, _ = make_service()
    if unexpected_access:
        service.vault_get = AsyncMock(return_value={'data': {'password': 'CANARY_PASSWORD'}})
    with span('verification.localized_probe'):
        tid = trace_id()
        output = await service.permission_probe(Session('probe', language=language))
    probe = next(r['attributes'] for r in records_for({tid}) if r['name'] == 'permissions.probe')
    assert probe['probe.check_count'] == 9
    assert probe['probe.matches_expected'] is (not unexpected_access)
    assert 'CANARY' not in output
    assert ('Vault permission check' if language == 'en' else 'Comprobación de permisos en Vault') in output
