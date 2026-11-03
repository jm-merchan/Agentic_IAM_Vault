from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import httpx
import jwt
import pytest

from app.vault_clock import jwt_clock_offset, raise_for_clock_mismatch, VaultClockSkew

NOW = 1793710912


def token(**claims):
    return jwt.encode({'iat': NOW, 'nbf': NOW, 'exp': NOW+600, **claims}, 'synthetic-unit-key-for-clock-tests-only', algorithm='HS256')


def response(offset=0, status=403):
    return httpx.Response(status, headers={'date': format_datetime(datetime.fromtimestamp(NOW+offset, timezone.utc), usegmt=True)})


def test_observed_writer_failure_is_identified_without_granting_access():
    assert jwt_clock_offset(response(-2005), token(), now=NOW) == -2005
    assert jwt_clock_offset(response(2005), token(), now=NOW) == 2005


@pytest.mark.parametrize('offset,status,claims', [
    (0, 403, {}), (15, 403, {}), (29, 403, {}), (-2005, 200, {}),
    (-2005, 500, {}), (-2005, 403, {'exp': NOW-1}),
    (-2005, 403, {'nbf': NOW+300}), (-60, 403, {'nbf': NOW-300}),
])
def test_policy_denials_expired_tokens_and_successes_are_not_clock_errors(offset, status, claims):
    assert jwt_clock_offset(response(offset, status), token(**claims), now=NOW) is None


@pytest.mark.parametrize('value', [None, True, float('nan'), '1793710912'])
def test_malformed_claims_do_not_change_the_original_denial(value):
    assert jwt_clock_offset(response(-2005), token(nbf=value), now=NOW) is None


def test_native_operator_and_missing_or_invalid_date_remain_ordinary_denials():
    assert jwt_clock_offset(response(-2005), 'hvs.synthetic-native', now=NOW) is None
    for headers in ({}, {'date': 'invalid'}):
        assert jwt_clock_offset(httpx.Response(403, headers=headers), token(), now=NOW) is None


def test_exception_and_telemetry_contain_clock_evidence_without_credentials(monkeypatch):
    monkeypatch.setattr('app.vault_clock.time.time', lambda: NOW)
    current = Mock()
    bearer = token()
    with pytest.raises(VaultClockSkew, match='2005 s') as error:
        raise_for_clock_mismatch(response(-2005), bearer, current)
    assert bearer not in str(error.value)
    current.set_attribute.assert_called_once_with('vault.clock.offset_seconds', -2005)


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,status,error', [(-2005, 403, VaultClockSkew), (0, 403, 'policy'), (-2005, 200, None)])
async def test_vault_request_reports_actual_failure_and_never_retries(monkeypatch, offset, status, error):
    from app.services import Services, VaultPermissionDenied
    monkeypatch.setattr('app.vault_clock.time.time', lambda: NOW)
    services = object.__new__(Services)
    services.config = {'vault_addr': 'https://vault.test'}
    services.vault_tls = True
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers=response(offset).headers,
                              json={'errors': ['permission denied']} if status == 403 else {'data': {}})
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(respond)))
    if error:
        with pytest.raises(VaultPermissionDenied if error == 'policy' else error):
            await services.vault_get('database/creds/chatbot-readonly', token())
    else:
        assert await services.vault_get('database/creds/chatbot-readonly', token()) == {'data': {}}
    assert len(calls) == 1
