import asyncio
import copy
import ssl
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.model_config import model_config, model_profiles, select_provider
from app.security import AccessDenied, Session, load_config
from app.services import Services


def profiles():
    return {
        'openai': {'provider': 'openai', 'model': 'gpt-4.1-nano', 'credential_source': 'vault_spiffe',
                   'identity_provider_id': 'idp-openai', 'service_account_id': 'account-openai'},
        'anthropic': {'provider': 'anthropic', 'model': 'claude-haiku-5-5', 'credential_source': 'vault_spiffe',
                      'federation_rule_id': 'rule-claude', 'organization_id': 'org-claude',
                      'service_account_id': 'account-claude', 'workspace_id': 'workspace-claude'},
        'xai': {'provider': 'xai', 'model': 'grok-4.3', 'credential_source': 'vault_dynamic'},
    }


def configuration():
    models = profiles()
    return {'models': models, 'model': dict(models['openai'])}


def session(sid='one'):
    return Session(sid, subject=sid, expires_at=time.time() + 600)


def test_selection_is_per_session_and_keeps_history():
    config = configuration(); original = copy.deepcopy(config)
    first, second = session(), session('two')
    first.messages = [{'role': 'user', 'content': 'Compara las tarifas'}]
    for provider in ('xai', 'anthropic', 'openai'):
        select_provider(config, first, provider)
        assert model_config(config, first.model_provider)['provider'] == provider
        assert model_config(config, second.model_provider)['provider'] == 'openai'
        assert first.messages[0]['content'] == 'Compara las tarifas'
    assert config == original


@pytest.mark.parametrize('provider', ['unknown', 'claude', '../../xai', '', None])
def test_untrusted_selection_is_rejected(provider):
    # The browser must send an explicit allowlisted ID, never fall back on bad input.
    config = configuration(); current = session()
    with pytest.raises(AccessDenied):
        select_provider(config, current, provider)
    assert current.model_provider == ''


def test_expired_session_and_missing_provider_fail_closed():
    config = configuration(); current = session(); current.expires_at = 0
    with pytest.raises(AccessDenied): select_provider(config, current, 'xai')
    current.expires_at = time.time() + 600
    del config['models']['xai']
    with pytest.raises(AccessDenied): select_provider(config, current, 'xai')
    config['models']['anthropic']['provider'] = 'openai'
    with pytest.raises(AccessDenied): select_provider(config, current, 'anthropic')


def test_legacy_config_remains_usable_without_cross_provider_fallback():
    config = {'model': profiles()['xai']}
    assert list(model_profiles(config)) == ['xai']
    assert model_config(config)['provider'] == 'xai'
    with pytest.raises(AccessDenied): model_config(config, 'openai')


@pytest.mark.asyncio
async def test_concurrent_federated_calls_use_their_own_exchange_ids(monkeypatch):
    config = configuration(); original = copy.deepcopy(config)
    service = object.__new__(Services); service.config = config
    service.mint_openai_identity = AsyncMock(return_value=('openai-svid', {'exp': time.time()+300}))
    service.mint_anthropic_identity = AsyncMock(return_value=('claude-svid', {'exp': time.time()+300}))
    requests = []
    async def handle(request):
        import json
        payload = json.loads(request.content)
        requests.append(payload)
        await asyncio.sleep(0)
        if request.url.host == 'auth.openai.com':
            assert payload['subject_token'] == 'openai-svid'
            assert payload['service_account_id'] == 'account-openai'
            assert payload['identity_provider_id'] == 'idp-openai'
            return httpx.Response(200, json={'access_token': 'openai-temporary', 'token_type': 'Bearer',
                                            'expires_at': time.time()+300})
        assert payload['assertion'] == 'claude-svid'
        assert payload['service_account_id'] == 'account-claude'
        assert payload['federation_rule_id'] == 'rule-claude'
        return httpx.Response(200, json={'access_token': 'claude-temporary', 'token_type': 'Bearer',
                                        'expires_in': 300, 'scope': 'workspace:developer'})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_client(transport=httpx.MockTransport(handle)))
    one, two = session(), session('two')
    select_provider(config, two, 'anthropic')
    results = await asyncio.gather(service.model_credentials(one), service.model_credentials(two))
    assert [r[0]['api_key'] for r in results] == ['openai-temporary', 'claude-temporary']
    assert [r[0]['provider'] for r in results] == ['openai', 'anthropic']
    assert len(requests) == 2 and config == original


@pytest.mark.parametrize('missing', [None, 'anthropic'])
def test_bootstrap_loads_every_agent_and_always_revokes_token(monkeypatch, missing):
    models = profiles()
    for profile in models.values(): profile['api_key'] = 'must-be-removed'
    calls = []
    def handle(request):
        calls.append(request.url.path)
        assert request.headers['X-Vault-Token'] == 'bootstrap-test'
        if request.url.path.endswith('/revoke-self'): return httpx.Response(204)
        if request.url.path.endswith('/task-agents'): return httpx.Response(404)
        name = request.url.path.rsplit('/', 1)[-1]
        if name == missing: return httpx.Response(403)
        value = {**models['openai'], 'providers': models} if name == 'model' else {'client_id': name}
        return httpx.Response(200, json={'data': {'data': value}})
    client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: client(transport=httpx.MockTransport(handle)))
    context = ssl.create_default_context()
    monkeypatch.setattr(ssl, 'create_default_context', lambda **kw: context)
    monkeypatch.setenv('CHATBOT_BOOTSTRAP_TOKEN', 'bootstrap-test')
    if missing:
        with pytest.raises(RuntimeError, match=missing): load_config()
    else:
        config = load_config()
        assert set(config['models']) == {'openai', 'xai', 'anthropic'}
        assert all(config[p]['client_id'] == p for p in models)
        assert all('api_key' not in p for p in config['models'].values())
        assert 'api_key' not in config['model']
    assert calls[-1] == '/v1/auth/token/revoke-self'


@pytest.mark.parametrize('default', ['auto', 'anthropic'])
def test_catalog_publisher_keeps_all_profiles(tmp_path, default):
    import json
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    state = tmp_path / 'state'; (state / 'vault').mkdir(parents=True)
    (state / 'vault/config.env').write_text('VAULT_ADDR=https://vault.test\nVAULT_TOKEN=test\nVAULT_CACERT=/tmp/test.ca\n')
    env_file = tmp_path / '.env'
    values = {'VERIFY_TENANT':'https://test.verify.ibm.com', 'NGROK_DOMAIN':'issuer.example',
              'OPENAI_IDENTITY_PROVIDER_ID':'idp', 'OPENAI_SERVICE_ACCOUNT_ID':'openai-account',
              'ANTHROPIC_FEDERATION_RULE_ID':'rule','ANTHROPIC_ORGANIZATION_ID':'org',
              'ANTHROPIC_SERVICE_ACCOUNT_ID':'claude-account', 'ANTHROPIC_WORKSPACE_ID':'workspace',
              'LUMEN_MODEL_PROVIDER':default}
    env_file.write_text(''.join(f'{key}={value}\n' for key,value in values.items()))
    bindir=tmp_path / 'bin'; bindir.mkdir()
    vault=bindir/'vault'
    vault.write_text('''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ['kv','get']:
    print(json.dumps({'data':{'data':{'client_id':'fixture','client_secret':'synthetic-only'}}}))
elif sys.argv[1:3] == ['kv','put']:
    assert sys.argv[4:] == ['chatbot/model','-']
    with open(os.environ['TEST_CATALOG'], 'w') as f: f.write(sys.stdin.read())
else: raise SystemExit(2)
'''); vault.chmod(0o700)
    target=tmp_path/'catalog.json'
    env={k:v for k,v in os.environ.items() if not k.startswith(('LUMEN_', 'OPENAI_', 'ANTHROPIC_'))}
    env.update(PATH=str(bindir)+os.pathsep+os.environ['PATH'], DEMO_ENV_FILE=str(env_file),
               LUMEN_STATE_DIR=str(state), TEST_CATALOG=str(target))
    result=subprocess.run(['bash',str(root/'chatbot/scripts/configure-models.sh')],env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    catalog=json.loads(target.read_text())
    assert set(catalog['providers']) == {'openai','xai','anthropic'}
    assert catalog['provider'] == ('openai' if default=='auto' else default)
    assert catalog['providers']['openai']['model'] == 'gpt-4.1-nano'
    assert catalog['providers']['anthropic']['service_account_id'] == 'claude-account'
    assert 'synthetic-only' not in target.read_text()+result.stdout+result.stderr
