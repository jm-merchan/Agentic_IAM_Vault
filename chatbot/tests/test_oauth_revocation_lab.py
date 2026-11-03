"""Prevent expiry, identity or policy mismatches from looking like revocation."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/verify-oauth-revocation.py'
spec = importlib.util.spec_from_file_location('oauth_revocation_lab', path)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


def test_api_exp_is_remaining_duration_plus_clock_tolerance():
    payload = lab.revocation_payload({'iss': lab.ISSUER, 'jti': 'jwt-a', 'exp': 1_800_000_600.25},
                                     now=1_800_000_000, leeway=15)
    assert payload == {'issuer': lab.ISSUER, 'unique_id': 'jwt-a', 'exp': 616}
    assert 'token' not in payload


@pytest.mark.parametrize('change', [{'jti': ''}, {'jti': None}, {'iss': ''},
                                  {'exp': 100}, {'exp': float('nan')}, {'exp': True}])
def test_invalid_or_expired_jwt_cannot_become_a_revocation_target(change):
    claims = {'iss': lab.ISSUER, 'jti': 'jwt-a', 'exp': 200, **change}
    with pytest.raises(ValueError):
        lab.revocation_payload(claims, now=100)


@pytest.mark.parametrize('status,observed_at', [(401, 100), (200, 100), (403, 170), (403, 201)])
def test_expiry_or_other_errors_cannot_be_reported_as_revocation(status, observed_at):
    with pytest.raises(AssertionError):
        lab.assert_live_denial(status, {'exp': 200}, observed_at)


def test_live_403_is_accepted():
    lab.assert_live_denial(403, {'exp': 200}, 100)


@pytest.mark.parametrize('mode', ['delegated', 'direct'])
@pytest.mark.parametrize('wrong', ['subject', 'issuer', 'rar', 'actor', 'same_jti'])
def test_control_pair_must_isolate_token_id_as_the_changed_input(mode, wrong):
    subject = 'writer' if mode == 'delegated' else 'agent'
    rar = [{'type': 'vault:path_access', 'path': lab.PATHS[mode], 'capabilities': ['read']}]
    a = {'iss': lab.ISSUER, 'sub': subject, 'jti': 'a', 'authorization_details': rar}
    if mode == 'delegated':
        a['actor-token'] = {'sub': 'agent'}
    b = deepcopy(a);b['jti'] = 'b'
    if wrong == 'subject':b['sub'] = 'different'
    if wrong == 'issuer':b['iss'] = 'https://untrusted.example'
    if wrong == 'rar':b['authorization_details'] = []
    if wrong == 'actor':b['actor-token'] = {'sub': 'different'}
    if wrong == 'same_jti':b['jti'] = a['jti']
    with pytest.raises(AssertionError):
        lab.assert_pair(a, b, mode=mode, subject=subject, actor='agent', rar=rar)


@pytest.mark.parametrize('field', ['issuer', 'unique_id'])
def test_operator_policy_cannot_expand_a_jwt_identifier_into_a_glob(field):
    payload = {'issuer': lab.ISSUER, 'unique_id': 'jwt-a', 'exp': 600, field: '*'}
    with pytest.raises(ValueError):
        lab.operator_policy(payload)
