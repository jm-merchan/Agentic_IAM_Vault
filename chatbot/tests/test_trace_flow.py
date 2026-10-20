import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from app.trace_flow import build_flow
from app.telemetry import records_for, span, trace_id
from app.services import Services
from app.security import AccessDenied, Session


def record(name, sid, start, end, parent=None, status='UNSET', **attrs):
    return dict(name=name, span_id=sid, parent_id=parent, start_ns=int(start * 1e6),
                end_ns=int(end * 1e6), duration_ms=end-start, status=status, attributes=attrs)


def legacy_list():
    return [
        record('lumen.applications.list', 'root', 0, 493.55),
        record('application.list_masked', 'masked', 0, 493.39, 'root'),
        record('data.access', 'data', 0, 493.22, 'masked'),
        record('verify.obo_exchange', 'obo', 0, 442.02, 'data',
               **{'vault.path': 'database/creds/chatbot-readonly', 'http.response.status_code': 200}),
        record('verify.client_credentials', 'cc', 0, 185.12, 'obo',
               **{'agent.identity': 'chatbot-oidc', 'http.response.status_code': 200}),
        record('vault.read', 'vault', 443, 476.47, 'data',
               **{'vault.path': 'database/creds/chatbot-readonly', 'http.response.status_code': 200}),
        record('mysql.query', 'sql', 476, 492.57, 'data',
               **{'db.operation.name': 'SELECT', 'db.role': 'readonly', 'db.namespace': 'scripting'}),
    ]


def test_screenshot_trace_has_four_calls_in_dependency_order_and_no_llm():
    flow = build_flow(list(reversed(legacy_list())))
    assert [c['name'] for c in flow['calls']] == [
        'verify.client_credentials', 'verify.obo_exchange', 'vault.read', 'mysql.query']
    assert [a['id'] for a in flow['actors']] == ['lumen', 'verify', 'vault', 'mysql']
    assert flow['duration_ms'] == 493.55
    assert flow['model_calls'] == 0
    assert len(flow['local']) == 3
    assert flow['calls'][1]['duration_ms'] == 442.02
    assert 'inclusiva' in flow['calls'][1]['notes'][0]
    assert 'readonly' in flow['calls'][-1]['credential']


def test_separate_sts_span_replaces_inclusive_wrapper_without_double_counting():
    records = legacy_list() + [record('verify.token_exchange', 'sts', 186, 441, 'obo',
                                     **{'http.response.status_code': 200})]
    flow = build_flow(records)
    assert len(flow['calls']) == 4
    assert flow['calls'][1]['name'] == 'verify.token_exchange'
    assert flow['calls'][1]['start_ms'] == 186
    assert flow['calls'][1]['duration_ms'] == 255
    assert flow['calls'][1]['notes'] == []
    assert any(r['name'] == 'verify.obo_exchange' for r in flow['local'])


def test_failure_before_sts_never_invents_a_second_verify_request():
    records = legacy_list()[:5]
    records[3]['attributes'].pop('http.response.status_code')
    records[3]['status'] = 'ERROR'
    records[4]['attributes']['http.response.status_code'] = 401
    records[4]['status'] = 'ERROR'
    flow = build_flow(records)
    assert len(flow['calls']) == 1
    assert flow['calls'][0]['status'] == 'Error · HTTP 401'
    assert flow['calls'][0]['response_recorded']
    assert flow['local_errors'] == 1


def test_login_validation_before_network_is_local_but_a_recorded_exchange_is_visible():
    failed = record('verify.oidc_login', 'login', 0, 1, status='ERROR')
    assert build_flow([failed])['calls'] == []
    completed = record('verify.oidc_login', 'login', 0, 100, **{'http.response.status_code': 200})
    assert build_flow([completed])['calls'][0]['target'] == 'verify'


@pytest.mark.parametrize('status,code,label', [
    ('UNSET', 403, 'Error · HTTP 403'), ('ERROR', 200, 'Error · HTTP 200'),
    ('ERROR', None, 'Error registrado'), ('UNSET', None, 'Sin error registrado'),
])
def test_status_does_not_turn_unset_or_http_200_into_an_authorization_claim(status, code, label):
    item = record('vault.read', 'v', 0, 50, status=status, **{'http.response.status_code': code})
    call = build_flow([item])['calls'][0]
    assert call['status'] == label
    assert call['response_recorded'] == bool(code)


@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'xai'])
def test_provider_calls_remain_separate_and_repeated_calls_are_preserved(provider):
    records = [record(provider + '.chat', str(i), i*100, i*100+90,
                      **{'gen_ai.request.model': 'test-model'}) for i in range(2)]
    flow = build_flow(records)
    assert flow['model_calls'] == 2
    assert [c['number'] for c in flow['calls']] == [1, 2]
    assert all(c['target'] == provider and c['method'] == 'SDK' for c in flow['calls'])


def test_new_flow_payload_does_not_copy_raw_captures_or_unknown_attributes():
    records = legacy_list()
    for r in records:
        r['attributes'].update({
            'vault.http.request': '{"Authorization":"CANARY_SECRET"}',
            'vault.http.response': '{"password":"CANARY_SECRET"}',
            'vault.auth.jwt': 'CANARY_SECRET', 'gen_ai.input.messages': 'CANARY_SECRET',
            'unknown.future.field': 'CANARY_SECRET',
        })
    original = copy.deepcopy(records)
    assert 'CANARY_SECRET' not in json.dumps(build_flow(records))
    assert records == original


def test_missing_parent_and_unknown_operation_remain_visible_without_inventing_destination():
    flow = build_flow([record('unknown.operation', 'u', 0, 50, 'missing')])
    assert flow['incomplete']
    assert flow['calls'] == []
    assert flow['local'][0]['name'] == 'unknown.operation'
    assert build_flow([])['duration_ms'] == 0


def test_public_jwks_call_is_separate_from_minting_and_never_uses_a_bearer():
    flow = build_flow([record('vault.jwks', 'jwks', 0, 10, **{'http.response.status_code': 200})])
    call = flow['calls'][0]
    assert call['endpoint'] == '/v1/spiffe/.well-known/keys'
    assert call['credential'].startswith('Sin token')


def test_classifier_and_answer_are_distinguished_using_the_recorded_parent():
    records = [record('deepagents.run', 'root', 0, 100),
               record('guardrail.energy_scope', 'guard', 0, 40, 'root'),
               record('anthropic.chat', 'scope', 1, 39, 'guard'),
               record('anthropic.chat', 'answer', 41, 99, 'root')]
    calls = build_flow(records)['calls']
    assert calls[0]['title'] == 'Clasificar la pregunta'
    assert calls[1]['title'] == 'Consultar el modelo'
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('http_status', [200, 401])
async def test_real_exchange_instrumentation_measures_sts_after_actor_token(monkeypatch, http_status):
    services = object.__new__(Services)
    services.config = {'oidc': {'client_id': 'actor'}, 'sts': {'client_id': 'sts', 'client_secret': 'test-only'}}
    path = 'database/creds/chatbot-readonly'
    services.identity = SimpleNamespace(validate=lambda *_: {
        'sub': 'user', 'actor-token': {'sub': 'actor'},
        'authorization_details': [{'type': 'vault:path_access', 'path': path, 'capabilities': ['read']}],
    })

    async def actor_token(_):
        with span('verify.client_credentials', **{'http.response.status_code': 200}):
            return 'synthetic-actor'

    services.client_token = actor_token
    transport = httpx.MockTransport(lambda _: httpx.Response(http_status, json={'access_token': 'synthetic-exchanged'}))
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=transport, **kwargs))
    session = Session('s', subject='user', access_token='synthetic-user', expires_at=time.time()+60)
    with span('lumen.action'):
        tid = trace_id()
        if http_status == 200:
            assert await services.exchange(session, path) == 'synthetic-exchanged'
        else:
            with pytest.raises(AccessDenied):
                await services.exchange(session, path)
    records = records_for({tid})
    actor = next(r for r in records if r['name'] == 'verify.client_credentials')
    sts = next(r for r in records if r['name'] == 'verify.token_exchange')
    assert sts['start_ns'] >= actor['end_ns']
    assert sts['parent_id'] == actor['parent_id']
    flow = build_flow(records)
    assert len(flow['calls']) == 2
    assert flow['calls'][1]['http_status'] == http_status
