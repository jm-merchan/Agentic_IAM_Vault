import base64
import json
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.applications import ApplicationServices, DEMO_FORM, validate_form
from app.security import AccessDenied, Session, role_for_groups


@pytest.mark.parametrize('field,value', [('dni', '12345678A'), ('dni', 'BAD'),
    ('iban', 'ES9021000418450200051332'), ('iban', 'ES123'), ('postal_code', '99000'),
    ('email', 'bad'), ('phone', '123'), ('plan_id', 99)])
def test_invalid_form_is_rejected(field, value):
    with pytest.raises(AccessDenied):
        validate_form({**DEMO_FORM, field: value})


def test_valid_document_and_iban_normalization():
    result = validate_form({**DEMO_FORM, 'dni': ' 12345678-z ', 'iban': 'es91 2100 0418 4502 0005 1332'})
    assert result['dni'] == DEMO_FORM['dni'] and result['iban'] == DEMO_FORM['iban']
    assert validate_form({**DEMO_FORM, 'dni': 'X1234567L'})['dni'] == 'X1234567L'


def service(role='readwrite'):
    item = ApplicationServices()
    item.config = {'runtime': {'groups': {'sensitive': ['supervisors']}}}
    item.role = lambda session: role
    item.database = AsyncMock(return_value=[])
    item.exchange = AsyncMock(return_value='test-token')
    item.vault_post = AsyncMock(side_effect=[{'data': {'ciphertext': 'vault:v1:test-ciphertext'}},
        {'data': {'encoded_value': 'random-dni-token'}}, {'data': {'encoded_value': 'random-iban-token'}}])
    item.event = lambda *args: None
    return item


@pytest.mark.asyncio
async def test_only_ciphertext_tokens_and_masked_hints_reach_sql():
    item = service()
    session = Session('s', subject='writer', expires_at=time.time() + 100)
    reference = str(uuid4())
    assert await item.save_application(session, DEMO_FORM, reference) == reference
    assert [c.args[1:] for c in item.exchange.call_args_list] == [
        ('transit/encrypt/lumen-applications', ['update']),
        ('transform/encode/lumen-dni', ['update']),
        ('transform/encode/lumen-iban', ['update'])]
    profile = json.loads(base64.b64decode(item.vault_post.call_args_list[0].args[2]['plaintext']))
    assert profile['full_name'] == DEMO_FORM['full_name']
    assert 'dni' not in profile and 'iban' not in profile
    insert = item.database.call_args_list[-1]
    assert insert.kwargs['write'] is True
    params = json.dumps(insert.args[2])
    for field in ('dni', 'iban', 'full_name', 'street', 'email', 'phone'):
        assert DEMO_FORM[field] not in params
    assert 'vault:v1:' in params and 'random-dni-token' in params


@pytest.mark.asyncio
async def test_readonly_cannot_save_even_bypassing_ui():
    item = service('readonly')
    with pytest.raises(AccessDenied):
        await item.save_application(Session('s'), DEMO_FORM, str(uuid4()))
    item.exchange.assert_not_called()
    item.database.assert_not_called()


@pytest.mark.asyncio
async def test_failed_protection_never_inserts_partial_data():
    item = service()
    item.vault_post.side_effect = AccessDenied('Vault denied')
    with pytest.raises(AccessDenied):
        await item.save_application(Session('s', subject='writer'), DEMO_FORM, str(uuid4()))
    assert len(item.database.call_args_list) == 1
    assert not item.database.call_args.kwargs.get('write')


@pytest.mark.asyncio
async def test_retry_after_saved_request_does_not_duplicate_or_reprotect():
    item = service()
    reference = str(uuid4())
    item.database.return_value = [{'application_id': reference}]
    assert await item.save_application(Session('s', subject='writer'), DEMO_FORM, reference) == reference
    item.exchange.assert_not_called()
    assert len(item.database.call_args_list) == 1


@pytest.mark.asyncio
async def test_reveal_returns_no_partial_result_when_vault_denies():
    item = service('readonly')
    item.database.return_value = [{'profile_ciphertext': 'vault:v1:encrypted', 'dni_token': 'd', 'iban_token': 'i'}]
    item.vault_post.side_effect = AccessDenied('Vault denied')
    with pytest.raises(AccessDenied):
        await item.reveal_application(Session('s'), str(uuid4()))
    assert item.exchange.call_args.args[1:] == ('transit/decrypt/lumen-applications', ['update'])


def test_supervisor_has_ro_database_and_separate_reveal_membership():
    session = Session('s', subject='supervisor', groups=['supervisors'], expires_at=time.time() + 100)
    assert role_for_groups(session.groups, {'sensitive': ['supervisors']}) == 'readonly'
    assert service('readonly').can_reveal(session)
    session.groups = ['writers']
    assert not service().can_reveal(session)
