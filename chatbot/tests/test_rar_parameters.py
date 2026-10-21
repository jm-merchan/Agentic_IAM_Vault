import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from app.i18n import EN, safe_return_path
from app.rar import LAB_CONTEXT, authorization_details
from app.rar_lab import interpretation, run_comparison, scenarios
from app.security import AccessDenied, Session
from app.services import Services, VaultPermissionDenied, VaultResponseError
from app.telemetry import span, records_for, trace_id
from app.trace_flow import build_flow

ROOT = Path(__file__).resolve().parents[2]


def config():
    return {'oidc': {'client_id': 'actor-id'}, 'sts': {'client_id': 'sts-id', 'client_secret': 'synthetic'},
            'runtime': {'groups': {'readwrite': ['writers']}, 'rar_probe': {'version': 1,
                        'approved': {'ciphertext': 'vault:v1:approved'}, 'other': {'ciphertext': 'vault:v1:other'}}}}


def session():
    return Session('test', subject='human', groups=['writers'], access_token='synthetic-subject', expires_at=time.time()+300)


@pytest.mark.parametrize('parameters', [
    {'required_parameters': 'name'}, {'required_parameters': ['name', 'name']},
    {'required_parameters': [{}]}, {'allowed_parameters': {'plaintext': 'value'}},
    {'denied_parameters': []}, {'path': '*'}, {'allowed_parameters': {'value': [float('nan')]}}
])
def test_malformed_constraints_cannot_silently_fall_back_to_unrestricted_rar(parameters):
    with pytest.raises((ValueError, TypeError)):
        authorization_details('transit/encrypt/key', ['update'], parameters)


def test_legacy_rar_and_explicit_json_types_are_preserved():
    assert authorization_details('path') == [{'type': 'vault:path_access', 'path': 'path', 'capabilities': ['read']}]
    params = {'allowed_parameters': {'version': ['1', 1]}, 'denied_parameters': {'batch_input': []}, 'required_parameters': ['version']}
    result = authorization_details('path', ['update'], params)
    params['required_parameters'].clear()
    assert result[0]['required_parameters'] == ['version']
    assert result[0]['allowed_parameters']['version'] == ['1', 1]


@pytest.mark.asyncio
@pytest.mark.parametrize('tamper', [False, True])
async def test_verify_must_return_all_constraints_exactly(monkeypatch, tamper):
    services = object.__new__(Services)
    services.config = config()
    services.client_token = AsyncMock(return_value='synthetic-actor')
    services.event = lambda *a, **kw: None
    params = {'allowed_parameters': {'key_version': ['1']}, 'denied_parameters': {'batch_input': []}, 'required_parameters': ['key_version']}
    wanted = authorization_details('transit/encrypt/key', ['update'], params)
    issued = deepcopy(wanted)
    if tamper:
        del issued[0]['denied_parameters']
    services.identity = SimpleNamespace(validate=lambda *a: {'sub': 'human', 'actor-token': {'sub': 'actor-id'}, 'authorization_details': issued})
    def respond(request):
        body = parse_qs(request.content.decode())
        assert json.loads(body['authorization_details'][0]) == wanted
        assert body['subject_token'] == ['synthetic-subject']
        assert body['actor_token'] == ['synthetic-actor']
        return httpx.Response(200, json={'access_token': 'synthetic-obo'})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(respond)))
    if tamper:
        with pytest.raises(AccessDenied, match='no coincide'):
            await services.exchange(session(), 'transit/encrypt/key', ['update'], parameters=params)
    else:
        assert await services.exchange(session(), 'transit/encrypt/key', ['update'], parameters=params) == 'synthetic-obo'


@pytest.mark.parametrize('control,restricted,expected,outcome', [
    (200, 403, False, 'rar_denied'), (403, 403, False, 'baseline_denied'),
    (200, 200, False, 'not_enforced'), (200, 403, True, 'unexpected_denial'),
    (200, 200, True, 'allowed'), (None, 403, False, 'inconclusive'),
    (400, 403, False, 'inconclusive'), (200, 500, False, 'inconclusive'),
])
def test_only_a_successful_control_can_attribute_a_denial_to_parameters(control, restricted, expected, outcome):
    assert interpretation(control, restricted, expected) == outcome


@pytest.mark.asyncio
async def test_comparison_keeps_user_actor_path_and_payload_and_resets_context():
    s = session()
    service = SimpleNamespace(config=config(), role=lambda s: 'readwrite', event=lambda *a: None)
    service.exchange = AsyncMock(side_effect=['control', 'restricted'])
    observed = []
    async def post(path, token, body):
        observed.append((path, token, deepcopy(body), LAB_CONTEXT.get().copy()))
        if token == 'restricted':
            raise VaultPermissionDenied('denied')
        return {'data': {'ciphertext': 'vault:v1:synthetic'}}
    service.vault_post = post
    result = await run_comparison(service, s, 'denied', 'batch')
    assert result[0]['interpretation'] == 'rar_denied'
    assert observed[0][0] == observed[1][0]
    assert observed[0][2] == observed[1][2]
    assert [o[3]['rar.lab.phase'] for o in observed] == ['baseline', 'restricted']
    assert [c.args[0] for c in service.exchange.call_args_list] == [s, s]
    assert service.exchange.call_args_list[0].kwargs == {'parameters': None}
    assert service.exchange.call_args_list[1].kwargs == {'parameters': {'denied_parameters': {'batch_input': []}}}
    assert LAB_CONTEXT.get() == {}


@pytest.mark.asyncio
async def test_exchange_failure_is_not_a_vault_response_and_never_sends_unvalidated_token():
    service = SimpleNamespace(config=config(), role=lambda s: 'readwrite', event=lambda *a: None,
                              exchange=AsyncMock(side_effect=AccessDenied('Verify unavailable')), vault_post=AsyncMock())
    result = await run_comparison(service, session(), 'required', 'absent')
    assert result[0]['interpretation'] == 'inconclusive'
    assert result[0]['phases']['restricted']['status'] is None
    service.vault_post.assert_not_called()
    assert LAB_CONTEXT.get() == {}


def test_scenarios_translations_and_selection_are_available_in_both_languages():
    catalog = scenarios(config())
    assert len(catalog) == 6 and sum(len(s['cases']) for s in catalog.values()) == 17
    for scenario in catalog.values():
        assert scenario['title'] in EN and scenario['description'] in EN
        for case in scenario['cases']:
            assert case['label'] in EN and case['reason'] in EN
    catalog['combined']['parameters'].clear()
    assert scenarios(config())['combined']['parameters']
    assert safe_return_path('/laboratorio-rar') == '/laboratorio-rar'


def test_trace_shows_only_annotated_synthetic_context_and_never_the_token():
    attrs = {'vault.path': 'transit/encrypt/key', 'http.response.status_code': 403,
             'auth.rar.presented': json.dumps(authorization_details('path', ['update'], {'required_parameters': ['key_version']})),
             'vault.http.request': 'SYNTHETIC_SECRET_TOKEN'}
    with span('test.rar'):
        tid = trace_id()
        with span('vault.write', **attrs):
            pass
        with span('vault.write', **attrs, **{'rar.lab.phase': 'restricted', 'rar.lab.case': 'test', 'rar.lab.payload': '{"key_version":"0"}'}):
            pass
    flow = build_flow(records_for({tid}))
    assert flow['calls'][0]['rar'] is None
    assert flow['calls'][1]['rar']['authorization_details'][0]['required_parameters'] == ['key_version']
    assert flow['calls'][1]['rar']['payload'] == {'key_version': '0'}
    assert 'SYNTHETIC_SECRET_TOKEN' not in json.dumps(flow)


@pytest.mark.parametrize('known', [True, False])
def test_rar_schema_migration_is_idempotent_and_preserves_custom_metadata(tmp_path, known):
    schema = json.loads((ROOT/'verify/config/rar-schema.json').read_text())
    old = deepcopy(schema)
    for key in ('allowed_parameters', 'denied_parameters', 'required_parameters'):
        old['properties'].pop(key)
    if not known:
        old['properties']['custom'] = {'type': 'string'}
    original = {'id': 'existing', 'type': 'vault:path_access', 'schema': json.dumps(old),
                'description': 'preserve custom consent', 'inlineMode': True, 'consentInlineText': 'unchanged'}
    state = tmp_path/'state.json'; state.write_text(json.dumps(original))
    shell = '''set -euo pipefail
TMP_WORK="$1"; VERIFY_DIR="$2/verify"; export TMP_WORK VERIFY_DIR
fail() { echo "$*" >&2; exit 1; }
api() {
  if [ "$1" = GET ] && [ "$2" = /v1.0/auth-detail-types ]; then
    printf '[{"id":"existing","type":"vault:path_access"}]' > "$3"
  elif [ "$1" = GET ]; then cp "$TMP_WORK/state.json" "$3"
  elif [ "$1" = PUT ]; then cp "${5#@}" "$TMP_WORK/state.json"; echo PUT >> "$TMP_WORK/mutations"; printf '{}' > "$3"
  else exit 23; fi
}
source "$VERIFY_DIR/scripts/rar-common.sh"
configure_rar
configure_rar
'''
    result = subprocess.run(['bash', '-c', shell, 'test', str(tmp_path), str(ROOT)], capture_output=True, text=True)
    updated = json.loads(state.read_text())
    if known:
        assert result.returncode == 0, result.stderr
        assert json.loads(updated.pop('schema')) == schema
        original.pop('schema')
        assert updated == original
        assert (tmp_path/'mutations').read_text() == 'PUT\n'
    else:
        assert result.returncode != 0
        assert updated == original
        assert not (tmp_path/'mutations').exists()
