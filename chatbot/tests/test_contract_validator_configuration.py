"""A clean rebuild must resolve the configured existing Validator before writes."""
import importlib.util
from pathlib import Path

import httpx
import pytest


@pytest.mark.parametrize('explicit,configured,previous,expected', [
    (None, 'real@example.invalid', None, 'real@example.invalid'),
    ('override@example.invalid', 'configured@example.invalid', 'old', 'override@example.invalid'),
    (None, 'configured@example.invalid', 'old', 'configured@example.invalid'),
    (None, '', 'previous@example.invalid', 'previous@example.invalid'),
])
def test_clean_or_existing_install_resolves_validator_with_documented_precedence(
        monkeypatch, tmp_path, explicit, configured, previous, expected):
    monkeypatch.setenv('VERIFY_TENANT', 'https://verify.test')
    monkeypatch.setenv('LUMEN_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('LUMEN_CONTRACT_VALIDATOR', configured)
    source = Path(__file__).resolve().parents[1] / 'scripts/configure-contracts.py'
    spec = importlib.util.spec_from_file_location('contract_config_fixture', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Selected(Exception):
        pass

    def vault_response(request):
        assert request.method == 'GET', 'Selection must not mutate Vault'
        if request.url.path.endswith('/verify-admin'):
            return httpx.Response(200, json={'data': {'data': {'client_id': 'admin', 'client_secret': 'test-only'}}})
        if request.url.path.endswith('/contracts') and previous:
            return httpx.Response(200, json={'data': {'data': {'version': module.CONFIG_VERSION,
                                                             'validator_username': previous}}})
        return httpx.Response(404)

    def verify_response(request):
        if request.url.path == '/oauth2/token':
            return httpx.Response(200, json={'access_token': 'test-only'})
        assert request.method == 'GET' and request.url.path == '/v2.0/Users'
        assert request.url.params['filter'] == f'userName eq "{expected}"'
        raise Selected

    with httpx.Client(base_url='https://vault.test', transport=httpx.MockTransport(vault_response)) as vault, \
            httpx.Client(base_url='https://verify.test', transport=httpx.MockTransport(verify_response)) as verify:
        with pytest.raises(Selected):
            module.configure(vault, verify, validator=explicit)
