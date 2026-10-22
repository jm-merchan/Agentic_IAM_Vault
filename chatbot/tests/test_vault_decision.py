import copy
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import vault_decision as decision
from app.i18n import EN
from app.security import Session
from app.trace_flow import build_flow

TID, SID = 'a' * 32, 'b' * 16


def record(path='database/creds/chatbot-readonly', name='vault.read', code=200):
    now = time.time_ns()
    return dict(trace_id=TID, span_id=SID, parent_id=None, name=name,
                start_ns=now, end_ns=now + 1000000, duration_ms=1, status='UNSET',
                attributes={'vault.path': path, 'vault.namespace': 'verify', 'http.response.status_code': code})


def events(rec, *, allowed=True):
    auth = {'entity_id': 'human-entity', 'client_token': 'CANARY_TOKEN', 'policies': ['human', 'ceiling'],
            'metadata': {'actor_entity_id': 'agent-entity', 'actor_entity_name': 'agent',
                         'jwt_issuer': 'https://issuer.example',
                         'jwt_authorization_details': json.dumps([{
                             'type': 'vault:path_access', 'path': rec['attributes']['vault.path'],
                             'capabilities': ['read'], 'allowed_parameters': {'ciphertext': ['CANARY_CIPHER']},
                             'denied_parameters': {'batch_input': []}, 'required_parameters': ['ciphertext'],
                             'extra': 'CANARY_EXTRA'}]), 'unexpected': 'CANARY_METADATA'},
            'policy_results': {'allowed': allowed, 'granting_policies': [
                {'type': ''}, {'name': 'human', 'namespace_path': 'verify/'}, {'name': 'ceiling'}] if allowed else []}}
    return [dict(type=kind, time='2026-10-22T16:00:00Z', auth=copy.deepcopy(auth),
                 request={'id': 'c' * 36, 'path': rec['attributes']['vault.path'], 'operation': 'read',
                          'namespace': {'path': 'verify/'}, 'headers': {'traceparent': [f'00-{TID}-{SID}-01']},
                          'data': {'plaintext': 'CANARY_BODY'}}, response={'data': {'password': 'CANARY_PASSWORD'}})
            for kind in ('request', 'response')]


def test_real_evidence_is_projected_without_credentials_or_parameter_values():
    rec = record(); raw = events(rec); original = copy.deepcopy(raw)
    result = decision.explain(rec, raw)
    assert result['mode'] == 'obo' and result['audit_state'] == 'matched'
    assert result['evidence']['policy_allowed'] is True
    assert [p['name'] for p in result['evidence']['granting_policies']] == ['human', 'ceiling']
    assert result['evidence']['authorization_details'][0]['allowed_parameters'] == ['ciphertext']
    assert 'CANARY' not in json.dumps(result)
    assert raw == original


@pytest.mark.parametrize('path', ['secrets/data/other', 'sys/leases/lookup', 'identity/entity/id/123',
                                 'transit/encrypt/arbitrary', 'auth/token/revoke-self', 'custom/mount/operation'])
def test_any_vault_path_has_a_decision_not_only_demo_routes(path):
    rec = record(path, 'vault.write')
    assert build_flow([rec])['calls'][0]['target'] == 'vault'
    assert decision.explain(rec, events(rec))['audit_state'] == 'matched'


@pytest.mark.parametrize('mode', ['native', 'oauth', 'obo', 'root', 'login', 'public'])
def test_authentication_modes_do_not_apply_obo_to_every_request(mode):
    rec = record('auth/approle/login' if mode == 'login' else 'spiffe/.well-known/keys' if mode == 'public' else 'sys/test',
                 'vault.jwks' if mode == 'public' else 'vault.write')
    raw = events(rec)
    for event in raw:
        if mode != 'obo':
            event['auth']['metadata'].pop('actor_entity_id')
            event['auth']['metadata'].pop('actor_entity_name')
        if mode in ('native', 'root', 'login'):
            event['auth']['metadata'] = {}
        if mode == 'root':
            event['auth']['policies'] = ['root']
        if mode in ('login', 'public'):
            event.pop('auth')
    result = decision.explain(rec, raw)
    assert result['mode'] == mode
    assert result['mode_label'] in EN and result['logic'] in EN
    if mode == 'public':
        assert result['evidence']['policy_allowed'] is None


def test_denial_does_not_invent_a_failing_layer_and_http_failure_is_separate():
    rec = record(code=403)
    result = decision.explain(rec, events(rec, allowed=False))
    assert result['evidence']['policy_allowed'] is False
    assert 'no identifica' in result['decision']
    result = decision.explain(rec, events(rec, allowed=True))
    assert result['http_status'] == 403 and result['evidence']['policy_allowed'] is True
    assert 'respuesta HTTP' in result['decision']


@pytest.mark.parametrize('alteration', ['span', 'path', 'namespace', 'unrelated_body'])
def test_similar_or_injected_log_lines_are_not_other_calls_evidence(alteration):
    rec = record(); raw = events(rec)
    for e in raw:
        if alteration in ('span', 'unrelated_body'):
            e['request']['headers']['traceparent'] = ['00-' + 'd' * 32 + '-' + 'e' * 16 + '-01']
        if alteration == 'unrelated_body':
            e['request']['data']['traceparent'] = f'00-{TID}-{SID}-01'
        if alteration == 'path': e['request']['path'] += '-other'
        if alteration == 'namespace': e['request']['namespace']['path'] = 'other/'
    result = decision.explain(rec, raw)
    assert result['audit_state'] == 'missing' and result['evidence']['policy_allowed'] is None


def test_forwarded_and_duplicate_events_are_not_double_counted():
    rec = record(); raw = events(rec)
    forwarded = copy.deepcopy(raw)
    for e in forwarded: e['request']['id'] = 'forwarded'
    forwarded[1]['error'] = 'please forward to the active node'
    internal = copy.deepcopy(raw)
    for e in internal: e.pop('auth')
    result = decision.explain(rec, forwarded + internal + raw + copy.deepcopy(raw))
    assert result['audit_state'] == 'matched'
    assert result['evidence']['entity_id'] == 'human-entity'
    assert result['evidence']['request_id'] == 'c' * 36


def test_conflicting_copies_or_request_ids_remain_ambiguous():
    rec = record(); raw = events(rec)
    second = copy.deepcopy(raw)
    for e in second: e['request']['id'] = 'different'
    assert decision.explain(rec, raw + second)['audit_state'] == 'ambiguous'
    raw[1]['auth']['policy_results']['allowed'] = False
    assert decision.explain(rec, raw)['audit_state'] == 'ambiguous'


def test_request_id_fallback_and_partial_events_are_explicit():
    rec = record(); rec['attributes']['vault.request_id'] = 'c' * 36
    raw = events(rec)
    raw[0]['request']['headers'] = {}
    result = decision.explain(rec, raw[:1])
    assert result['audit_state'] == 'matched'
    assert result['evidence']['request_recorded'] and not result['evidence']['response_recorded']


@pytest.mark.parametrize('state', ['missing', 'unavailable', 'limited'])
def test_missing_evidence_does_not_backfill_current_configuration(state):
    result = decision.explain(record(code=403), [], state)
    assert result['mode'] == 'unknown' and result['audit_state'] == state
    assert not result['evidence']['policies'] and result['evidence']['policy_allowed'] is None
    assert 'no se puede atribuir' in result['decision']


def test_hmac_metadata_is_not_misrepresented_as_readable_identity_or_rar():
    rec = record(); raw = events(rec)
    for e in raw:
        e['auth']['entity_id'] = 'hmac-sha256:abcd'
        e['auth']['metadata'] = {'jwt_issuer': 'hmac-sha256:abcd', 'jwt_authorization_details': 'hmac-sha256:abcd'}
    result = decision.explain(rec, raw)
    assert result['mode'] == 'oauth'
    assert not result['evidence']['entity_id'] and not result['evidence']['authorization_details']


def client_for(rec):
    session = Session('owner', subject='user', expires_at=time.time() + 600, traces=[TID])
    identity = SimpleNamespace(sessions={'owner': session})
    app = FastAPI(); app.include_router(decision.decision_router(identity, lambda tids: [rec]))
    client = TestClient(app); client.cookies.set('lumen_session', 'owner')
    return client, identity, f'/traces/{TID}/steps/{SID}/vault-decision'


def test_route_is_session_owned_without_lab_raw_capture(monkeypatch):
    rec = record(); query = AsyncMock(return_value=(events(rec), 'available'))
    monkeypatch.setattr(decision, 'query_audit', query)
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '0')
    client, identity, url = client_for(rec)
    response = client.get(url)
    assert response.status_code == 200 and response.json()['audit_state'] == 'matched'
    assert response.headers['cache-control'] == 'no-store'
    assert 'CANARY' not in response.text
    query.reset_mock(); client.cookies.clear()
    assert client.get(url).status_code == 404
    client.cookies.set('lumen_session', 'owner')
    assert client.get(url.replace(TID, 'd' * 32)).status_code == 404
    assert client.get(url.replace(SID, 'e' * 16)).status_code == 404
    identity.sessions['owner'].expires_at = 0
    assert client.get(url).status_code == 404
    query.assert_not_called()


def test_session_expiry_during_audit_query_discards_result(monkeypatch):
    rec = record(); client, identity, url = client_for(rec)
    async def query(*args):
        identity.sessions.clear()
        return events(rec), 'available'
    monkeypatch.setattr(decision, 'query_audit', query)
    assert client.get(url).status_code == 404


def test_non_vault_steps_cannot_query_audit(monkeypatch):
    query = AsyncMock(); monkeypatch.setattr(decision, 'query_audit', query)
    client, _, url = client_for(record(name='verify.token_exchange'))
    assert client.get(url).status_code == 404
    query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['success', 'down', 'limited', 'bad_json', 'oversize'])
async def test_loki_query_is_bounded_and_fails_without_exposing_raw_values(monkeypatch, scenario):
    rec = record(); raw = events(rec)
    def handler(request):
        assert request.url.path == '/loki/api/v1/query_range'
        assert f'00-{TID}-{SID}-' in request.url.params['query']
        assert int(request.url.params['end']) - int(request.url.params['start']) == 10_001_000_000
        if scenario == 'down': return httpx.Response(503, text='CANARY_UPSTREAM')
        if scenario == 'bad_json': return httpx.Response(200, text='CANARY_UPSTREAM')
        if scenario == 'oversize': return httpx.Response(200, content=b'x' * 4_000_001)
        lines = [[str(rec['start_ns']), json.dumps(e)] for e in raw]
        if scenario == 'limited': lines *= 100
        return httpx.Response(200, json={'status': 'success', 'data': {'result': [{'values': lines}]}})
    factory = httpx.AsyncClient
    monkeypatch.setattr(decision.httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))
    records, state = await decision.query_audit(rec, 'http://localhost:3100')
    expected = {'success': 'available', 'down': 'unavailable', 'limited': 'limited', 'bad_json': 'unavailable', 'oversize': 'limited'}
    assert state == expected[scenario]
    if scenario != 'success': assert records == []


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], 'unexpected document', 42, None])
async def test_loki_non_object_json_is_unavailable_without_a_server_error(monkeypatch, payload):
    factory = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(payload)))
    monkeypatch.setattr(decision.httpx, 'AsyncClient', lambda **kwargs: factory(transport=transport, **kwargs))
    assert await decision.query_audit(record(), 'http://localhost:3100') == ([], 'unavailable')
