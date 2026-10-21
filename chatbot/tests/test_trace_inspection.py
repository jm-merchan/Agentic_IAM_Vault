import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import lab_capture
from app.security import Identity, Session
from app.services import Services
from app.telemetry import ModelSpans, span, trace_id, records_for
from app.trace_flow import build_flow
from app.trace_inspection import inspect_record, inspection_router


@pytest.fixture(autouse=True)
def capture_store(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    store = lab_capture.CaptureStore()
    monkeypatch.setattr(lab_capture, 'STORE', store)
    return store


def sections(record):
    return {s['key']: s['value'] for s in inspect_record(
        record, lab_capture.STORE.get(record['trace_id'], record['span_id']))}


def test_store_copies_bounds_and_expires(monkeypatch):
    clock = [1000]
    monkeypatch.setattr(lab_capture.time, 'time', lambda: clock[0])
    store = lab_capture.CaptureStore(ttl=10, capacity=2, max_bytes=1024)
    value = {'token': 'original'}
    store.put('t', 'a', 'response', 'Response', value)
    value['token'] = 'changed'
    copy = store.get('t', 'a')
    assert copy['sections']['response']['value']['token'] == 'original'
    copy['sections'].clear()
    assert store.get('t', 'a')['sections']
    store.put('t', 'b', 'response', 'Response', 'é😀' * 2000)
    large = store.get('t', 'b')['sections']['response']
    assert large['truncated'] and len(json.dumps(large['value'], ensure_ascii=False).encode()) <= 1024
    store.put('t', 'c', 'response', 'Response', {})
    assert store.get('t', 'a') is None
    clock[0] += 11
    assert store.get('t', 'b') is None and not store.entries


@pytest.mark.parametrize('mode', ['0', '1'])
def test_capture_is_opt_in_and_never_exported(monkeypatch, mode):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', mode)
    with span('verify.client_credentials') as current:
        tid = trace_id()
        lab_capture.capture(current, 'response', 'Token', {'access_token': 'CANARY_ACCESS'})
    record = records_for({tid})[0]
    found = sections(record)
    assert bool(found) == (mode == '1')
    assert 'CANARY_ACCESS' not in json.dumps(record)
    assert 'CANARY_ACCESS' not in json.dumps(build_flow([record]))


def test_endpoint_requires_authenticated_owner_and_matching_span(monkeypatch):
    with span('verify.client_credentials') as current:
        tid = trace_id()
        lab_capture.capture(current, 'response', 'Token', {'access_token': 'CANARY_ACCESS'})
    record = records_for({tid})[0]
    session = Session('owner', subject='user', expires_at=time.time() + 600)
    session.traces.append(tid)
    other = Session('other', subject='other', expires_at=time.time() + 600)
    identity = SimpleNamespace(sessions={'owner': session, 'other': other})
    app = FastAPI()
    app.include_router(inspection_router(identity, records_for))
    client = TestClient(app)
    url = f'/traces/{tid}/steps/{record["span_id"]}/sensitive'
    assert client.get(url).status_code == 404
    client.cookies.set('lumen_session', 'other')
    assert client.get(url).status_code == 404
    client.cookies.set('lumen_session', 'owner')
    result = client.get(url)
    assert result.status_code == 200 and 'CANARY_ACCESS' in result.text
    assert result.headers['cache-control'] == 'no-store'
    assert client.get(url.replace(record['span_id'], '0' * 16)).status_code == 404
    assert client.get(url.replace(tid, '0' * 32)).status_code == 404
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '0')
    assert client.get(url).status_code == 403
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    session.expires_at = time.time() - 1
    assert client.get(url).status_code == 404


def test_jwt_and_transit_decoding_preserve_original_and_do_not_invent():
    token = jwt.encode({'sub': 'workload', 'aud': 'test'}, 'test-signing-key-with-at-least-32-bytes', algorithm='HS256')
    plaintext = json.dumps({'name': 'Demostración', 'iban': 'FICTIONAL'})
    encoded = base64.b64encode(plaintext.encode()).decode()
    record = {'attributes': {
        'vault.http.request': json.dumps({'headers': {'X-Vault-Token': token}, 'body': {'plaintext': encoded}}),
        'vault.http.response': json.dumps({'body': {'data': {'ciphertext': 'vault:v1:ciphertext'}}}),
    }}
    evidence = inspect_record(record)
    assert evidence[0]['value']['body']['plaintext'] == encoded
    assert evidence[1]['value']['body']['data']['ciphertext'] == 'vault:v1:ciphertext'
    decoded = next(s for s in evidence if s['key'].startswith('decoded.'))['value']
    assert decoded['claims']['sub'] == 'workload' and decoded['signature_verified_by_decoder'] is False
    assert next(s for s in evidence if s['key'].startswith('plaintext.'))['value'] == plaintext
    record['attributes']['vault.http.request.truncated'] = True
    assert len(inspect_record(record)) == 2
    assert inspect_record({'attributes': {}}) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('client_secret', ['CANARY_CLIENT_SECRET', 'á:+/ &%😀', ''])
async def test_verify_capture_matches_request_and_response(monkeypatch, client_secret):
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={'access_token': 'CANARY_VERIFY', 'expires_in': 600})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler)))
    service = object.__new__(Services)
    service.config = {'oidc': {'client_id': 'agent', 'client_secret': client_secret}}
    with span('test.verify'):
        tid = trace_id()
        assert await service.client_token('oidc') == 'CANARY_VERIFY'
    record = next(r for r in records_for({tid}) if r['name'] == 'verify.client_credentials')
    found = sections(record)
    assert found['response']['body']['access_token'] == 'CANARY_VERIFY'
    assert found['request']['body']['grant_type'] == 'client_credentials'
    assert found['request']['client_id'] == 'agent'
    assert found['authentication']['client_secret'] == client_secret
    assert found['request']['authentication']['client_secret'] == client_secret
    assert found['authentication']['Authorization'] == sent[0].headers['authorization']
    assert found['request']['headers']['Authorization'] == sent[0].headers['authorization']
    assert base64.b64decode(sent[0].headers['authorization'].split()[1]).decode() == 'agent:' + client_secret
    if client_secret:
        assert client_secret not in json.dumps(records_for({tid}), ensure_ascii=False)
    assert sent[0].headers['authorization'] not in json.dumps(records_for({tid}))
    assert 'CANARY_VERIFY' not in json.dumps(records_for({tid}))


@pytest.mark.asyncio
async def test_oidc_login_captures_actual_basic_credentials_and_pkce(monkeypatch):
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={'id_token': 'id-canary', 'access_token': 'access-canary'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler)))
    identity = Identity({'oidc': {'client_id': 'oidc', 'client_secret': 'CANARY_LOGIN_SECRET'},
                         'runtime': {'groups': {}}})
    pending, _ = identity.start()
    verifier = pending.verifier
    identity.validate = lambda *args: {
        'sub': 'user', 'nonce': pending.nonce, 'may_act': {'client_id': 'oidc'},
        'exp': time.time() + 600, 'groups': [],
    }
    with span('test.login'):
        tid = trace_id()
        await identity.finish(pending.sid, pending.state, 'authorization-code')
    record = next(r for r in records_for({tid}) if r['name'] == 'verify.oidc_login')
    found = sections(record)
    assert found['authentication']['client_secret'] == 'CANARY_LOGIN_SECRET'
    assert found['request']['headers']['Authorization'] == sent[0].headers['authorization']
    assert found['request']['body']['code_verifier'] == verifier
    assert 'CANARY_LOGIN_SECRET' not in json.dumps(records_for({tid}))


def test_basic_credentials_are_not_captured_when_lab_capture_is_disabled(monkeypatch, capture_store):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '0')
    with span('verify.client_credentials') as current:
        tid = trace_id()
        lab_capture.request(current, 'POST', 'https://verify.test/token', {},
                            basic_auth=('client', 'CANARY_SECRET'))
    assert not capture_store.entries
    assert 'CANARY_SECRET' not in json.dumps(records_for({tid}))


@pytest.mark.asyncio
async def test_obo_captures_both_actual_input_tokens_and_result(monkeypatch):
    payloads = []
    sent = []
    def handler(request):
        from urllib.parse import parse_qs
        sent.append(request)
        payloads.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={'access_token': 'CANARY_OBO'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler)))
    service = object.__new__(Services)
    service.config = {'oidc': {'client_id': 'agent'}, 'sts': {'client_id': 'sts', 'client_secret': 'CANARY_STS_SECRET'}}
    path = 'database/creds/test'
    service.identity = SimpleNamespace(validate=lambda *args: {
        'sub': 'user', 'actor-token': {'sub': 'agent'},
        'authorization_details': [{'type': 'vault:path_access', 'path': path, 'capabilities': ['read']}]})
    service.client_token = AsyncMock(return_value='CANARY_ACTOR')
    service.event = lambda *args, **kwargs: None
    session = Session('owner', subject='user', access_token='CANARY_SUBJECT', expires_at=time.time() + 600)
    with span('test.obo'):
        tid = trace_id()
        assert await service.exchange(session, path) == 'CANARY_OBO'
    record = next(r for r in records_for({tid}) if r['name'] == 'verify.token_exchange')
    found = sections(record)
    for key in ('actor_token', 'subject_token', 'authorization_details'):
        assert found['request']['body'][key] == payloads[0][key][0]
    assert found['response']['body']['access_token'] == 'CANARY_OBO'
    assert found['authentication']['client_id'] == 'sts'
    assert found['authentication']['client_secret'] == 'CANARY_STS_SECRET'
    assert found['request']['headers']['Authorization'] == sent[0].headers['authorization']
    assert 'CANARY_' not in json.dumps(records_for({tid}))


@pytest.mark.asyncio
async def test_database_captures_actual_credential_query_and_result(monkeypatch):
    service = object.__new__(Services)
    service.role = lambda session: 'readwrite'
    service.config = {}
    service.event = lambda *args, **kw: None
    service.exchange = AsyncMock(return_value='obo')
    service.vault_get = AsyncMock(return_value={'lease_id': 'lease-test', 'lease_duration': 600,
        'data': {'username': 'dynamic-user', 'password': 'CANARY_SQL'}})
    observed = {}
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params): observed.update(sql=sql, params=params)
        def fetchmany(self, limit): return [{'plan': 'Plan ficticio'}]
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return Cursor()
    def connect(**kwargs):
        observed.update(kwargs)
        return Connection()
    monkeypatch.setattr('app.services.pymysql.connect', connect)
    with span('test.database'):
        tid = trace_id()
        result = await service.database(SimpleNamespace(task_agent='legacy'), 'SELECT plan WHERE id=%s', ('demo',))
    record = next(r for r in records_for({tid}) if r['name'] == 'mysql.query')
    found = sections(record)
    assert found['connection']['password'] == observed['password'] == 'CANARY_SQL'
    assert found['connection']['username'] == observed['user']
    assert found['query']['statement'] == observed['sql']
    assert found['query']['parameters'] == list(observed['params'])
    assert found['result'] == result
    assert 'CANARY_SQL' not in json.dumps(records_for({tid}))


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'xai'])
async def test_model_credential_is_only_in_its_own_call(provider):
    with span('test.model'):
        tid = trace_id()
        callback = ModelSpans('model', provider=provider, credential='CANARY_MODEL')
        await callback.on_chat_model_start({}, [[]], run_id=uuid4())
        callback.close()
    record = next(r for r in records_for({tid}) if r['name'] == provider + '.chat')
    assert sections(record)['authentication']['Authorization'] == 'Bearer CANARY_MODEL'
    assert callback.credential is None
    assert 'CANARY_MODEL' not in json.dumps(records_for({tid}))


def test_capture_labels_follow_page_language_without_altering_values():
    with span('verify.client_credentials') as current:
        tid = trace_id()
        lab_capture.capture(current, 'authentication', 'Autenticación HTTP Basic',
                            {'client_secret': 'Solicitud guardada', 'Authorization': 'Basic CANARY'})
    record = records_for({tid})[0]
    session = Session('owner', subject='user', expires_at=time.time()+600, traces=[tid])
    app = FastAPI()
    app.include_router(inspection_router(SimpleNamespace(sessions={'owner': session}), records_for))
    client = TestClient(app)
    client.cookies.set('lumen_session', 'owner')
    client.cookies.set('lumen_language', 'es')
    url = f'/traces/{tid}/steps/{record["span_id"]}/sensitive'
    english = client.get(url, headers={'X-Lumen-Language': 'en'}).json()
    spanish = client.get(url).json()
    assert english['sections'][0]['title'] == 'HTTP Basic authentication'
    assert spanish['sections'][0]['title'] == 'Autenticación HTTP Basic'
    assert english['sections'][0]['value'] == spanish['sections'][0]['value']
    assert english['sections'][0]['value']['client_secret'] == 'Solicitud guardada'
    client.cookies.clear()
    assert client.get(url, headers={'X-Lumen-Language': 'en'}).status_code == 404
