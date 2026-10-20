import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('claude_issuer', ROOT / 'scripts/demo/claude_issuer.py')
issuer_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(issuer_sync)
KEY = {'kty': 'RSA', 'kid': 'new-key', 'n': 'public-modulus', 'e': 'AQAB'}


class API:
    def __init__(self, *, persist=True):
        self.issuer = {'id': 'fdis_fixture', 'name': 'lumen', 'issuer_url': 'https://example/v1/verify/spiffe',
                       'check_jti': True, 'max_jwt_lifetime_seconds': 3600,
                       'jwks': {'type': 'inline', 'keys': [{**KEY, 'kid': 'old-key'}]}}
        self.rule = {'id': 'fdrl_fixture', 'issuer_id': 'fdis_fixture', 'oauth_scope': 'workspace:developer',
                     'target': {'service_account_id': 'svac_fixture'}}
        self.calls = []
        self.persist = persist

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path == '/federation_rules/fdrl_fixture':
            assert method == 'GET'
            return copy.deepcopy(self.rule)
        assert path == '/federation_issuers/fdis_fixture'
        if method == 'POST':
            assert set(payload) == {'jwks'}
            if self.persist:
                self.issuer.update(copy.deepcopy(payload))
        return copy.deepcopy(self.issuer)


def sync(api):
    return issuer_sync.sync(api, 'fdis_fixture', 'fdrl_fixture', 'svac_fixture',
                            'https://example/v1/verify/spiffe', [KEY])


def test_rotation_updates_keys_only_then_is_idempotent():
    api = API()
    original = copy.deepcopy(api.issuer)
    report = sync(api)
    assert report['updated'] and report['public_keys_match']
    assert api.issuer == {**original, 'jwks': {'type': 'inline', 'keys': [KEY]}}
    assert sync(api)['updated'] is False
    assert sum(method == 'POST' for method, _, _ in api.calls) == 1


@pytest.mark.parametrize('invalid', ['issuer_url', 'issuer_id', 'account', 'admin_rule'])
def test_mismatched_or_admin_identity_is_never_modified(invalid):
    api = API()
    if invalid == 'issuer_url':
        api.issuer['issuer_url'] = 'https://different'
    elif invalid == 'issuer_id':
        api.rule['issuer_id'] = 'fdis_another'
    elif invalid == 'account':
        api.rule['target']['service_account_id'] = 'svac_another'
    else:
        api.rule['oauth_scope'] = 'org:admin'
    with pytest.raises(ValueError, match='No se ha modificado'):
        sync(api)
    assert all(method == 'GET' for method, _, _ in api.calls)


def test_successful_post_without_persisted_keys_is_a_failure():
    with pytest.raises(ValueError, match='no conserva'):
        sync(API(persist=False))


def test_private_key_material_is_never_exported():
    assert issuer_sync.public_keys([{**KEY, 'd': 'PRIVATE', 'p': 'PRIVATE', 'q': 'PRIVATE'}]) == [KEY]


def test_cli_login_ignores_inference_credentials_and_refreshes_named_profile(tmp_path, monkeypatch):
    ant = tmp_path / 'ant'
    ant.write_text("""#!/usr/bin/env python3
import os, sys, json
assert not any(k in os.environ for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_FEDERATION_RULE_ID'))
assert sys.argv[1:] == ['auth', 'print-credentials', '--profile', 'lumen-admin', '--access-token']
print('SYNTHETIC-OAUTH-TOKEN')
""")
    ant.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_FEDERATION_RULE_ID'):
        monkeypatch.setenv(key, 'MUST-NOT-BE-USED')
    assert issuer_sync.admin_token('lumen-admin') == 'SYNTHETIC-OAUTH-TOKEN'


def test_auth_failure_does_not_print_cli_credentials(tmp_path, monkeypatch):
    ant = tmp_path / 'ant'
    ant.write_text("#!/bin/bash\necho PRIVATE-CANARY >&2\nexit 1\n")
    ant.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    with pytest.raises(ValueError) as error:
        issuer_sync.admin_token('lumen-admin')
    assert 'PRIVATE-CANARY' not in str(error.value)
    assert 'ant auth login --profile lumen-admin --scope org:admin' in str(error.value)
