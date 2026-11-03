import json
import time
from types import SimpleNamespace

import httpx
import jwt
import pymysql
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import lab_capture
from app.oauth_revocation_lab import Credential, OAuthRevocationLab, Pair, PATHS
from app.rar import authorization_details
from app.request_workbench import templates
from app.security import AccessDenied, ISSUER, Session
from app.telemetry import records_for, span, trace_id
from app.trace_inspection import inspect_record, inspection_router


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    store = lab_capture.CaptureStore()
    monkeypatch.setattr(lab_capture, 'STORE', store)
    return store


def manager():
    services = SimpleNamespace(config={'vault_addr': 'https://vault.test',
        'xai': {'client_id': 'agent', 'client_secret': 'CANARY_CLIENT_SECRET'}}, vault_tls=True)
    lab = OAuthRevocationLab(services, token='CANARY_OPERATOR_BEARER')
    pair = Pair('owner', 'human', 'direct', 'legacy')
    pair.claims = [{'iss': ISSUER, 'jti': 'A', 'exp': time.time()+600}]
    pair.credentials = [Credential(PATHS['direct']+'/lease-A', 300, time.monotonic()+300,
                                   time.time()+300, {'api_key': 'CANARY_XAI_KEY'})]
    return lab, pair


def mock_http(monkeypatch, handler):
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: factory(**kw, transport=httpx.MockTransport(handler)))


def captured(tid, name):
    record = next(r for r in records_for({tid}) if r['name'] == name)
    stored = lab_capture.STORE.get(tid, record['span_id'])
    assert stored
    return record, stored, {s['key']: s['value'] for s in inspect_record(record, stored)}


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', ['0', '1'])
async def test_workload_vault_capture_has_real_jwt_and_lease_but_never_operator_or_exported_secrets(capture, monkeypatch, enabled):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', enabled)
    lab, pair = manager()
    token = jwt.encode({'iss': ISSUER, 'sub': 'agent', 'jti': 'A', 'exp': time.time()+600},
                       'test-signing-key-with-at-least-32-bytes', algorithm='HS256')
    def respond(request):
        assert request.headers['x-vault-token'] == token
        return httpx.Response(200, json={'lease_id': pair.credentials[0].lease_id,
            'lease_duration': 300, 'data': {'api_key': 'CANARY_XAI_KEY'}})
    mock_http(monkeypatch, respond)
    with span('test.revocation'):
        tid = trace_id()
        await lab._request(pair, 'A', token, phase='before')
    if enabled == '1':
        record, stored, sections = captured(tid, 'vault.read')
        assert sections['http.request.1']['headers']['x-vault-token'] == token
        assert sections['http.response.1']['body']['data']['api_key'] == 'CANARY_XAI_KEY'
        assert any(s['value'].get('claims', {}).get('jti') == 'A'
                   for s in inspect_record(record, stored) if s['key'].startswith('decoded.'))
        assert templates(stored)[0]['headers']['x-vault-token'] == token
    else:
        assert not capture.entries
    exported = json.dumps(records_for({tid}))
    assert token not in exported and 'CANARY_' not in exported
    assert 'CANARY_OPERATOR_BEARER' not in json.dumps(list(capture.entries.values()))


@pytest.mark.asyncio
@pytest.mark.parametrize('lookup', [False, True])
async def test_operator_exchange_is_inspectable_without_bearer_or_replay(capture, monkeypatch, lookup):
    lab, pair = manager()
    def respond(request):
        assert request.headers['x-vault-token'] == 'CANARY_OPERATOR_BEARER'
        if lookup:
            return httpx.Response(400, json={'errors': ['invalid lease']})
        assert json.loads(request.content)['unique_id'] == 'A'
        return httpx.Response(200, json={})
    mock_http(monkeypatch, respond)
    with span('test.revocation'):
        tid = trace_id()
        if lookup:
            assert await lab._lookup(pair, 0, 'lease_after') == 'missing'
        else:
            await lab._request(pair, 'A', lab._token, revoke={'issuer': ISSUER, 'unique_id': 'A', 'exp': 615}, phase='revoke')
    record, stored, sections = captured(tid, 'vault.write')
    assert sections['request']['headers']['x-vault-token'] == '[REDACTED]'
    assert sections['replay_policy']['allowed'] is False
    assert not templates(stored)
    if lookup: assert sections['response']['body']['errors'] == ['invalid lease']
    assert 'CANARY_OPERATOR_BEARER' not in json.dumps(stored)
    assert 'CANARY_' not in json.dumps(records_for({tid}))
    session = Session('owner', subject='human', expires_at=time.time()+600, traces=[tid])
    app = FastAPI()
    app.include_router(inspection_router(SimpleNamespace(sessions={'owner': session}), records_for))
    with TestClient(app) as client:
        url = f'/traces/{tid}/steps/{record["span_id"]}/sensitive'
        assert client.get(url).status_code == 404
        client.cookies.set('lumen_session', 'owner')
        result = client.get(url)
        assert result.status_code == 200 and result.json()['sections']
        assert result.json()['replay_note'] and not result.json()['requests']
        assert result.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_direct_verify_capture_includes_signed_rar_request_and_real_response(capture, monkeypatch):
    lab, _ = manager()
    def respond(request):
        assert request.url.path == '/oauth2/token'
        return httpx.Response(200, json={'access_token': 'CANARY_DIRECT_JWT'})
    mock_http(monkeypatch, respond)
    with span('test.revocation'):
        tid = trace_id()
        assert await lab._direct() == 'CANARY_DIRECT_JWT'
    _, stored, sections = captured(tid, 'verify.client_credentials')
    assert sections['authentication']['client_secret'] == 'CANARY_CLIENT_SECRET'
    assert json.loads(sections['request']['body']['authorization_details']) == authorization_details(PATHS['direct'], ['read'])
    assert sections['http.response.1']['body']['access_token'] == 'CANARY_DIRECT_JWT'
    assert templates(stored)[0]['url'] == ISSUER + '/token'
    assert 'CANARY_' not in json.dumps(records_for({tid}))


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body,authentication', [(200, {'name': 'test-key'}, 'accepted'),
    (400, {'error': 'Invalid API key'}, 'rejected')])
async def test_xai_probe_has_exact_http_capture_on_success_and_auth_failure(capture, monkeypatch, code, body, authentication):
    lab, pair = manager()
    def respond(request):
        assert request.headers['authorization'] == 'Bearer CANARY_XAI_KEY'
        return httpx.Response(code, headers={'x-request-id': 'probe-request'}, json=body)
    mock_http(monkeypatch, respond)
    with span('test.revocation'):
        tid = trace_id()
        await lab._system(pair, 0, 'system_after')
    record, stored, sections = captured(tid, 'xai.auth_probe')
    assert sections['http.request.1']['url'] == 'https://api.x.ai/v1/api-key'
    assert sections['http.response.1']['body'] == body
    assert sections['http.response.1']['headers']['x-request-id'] == 'probe-request'
    assert record['attributes']['revocation.lab.authentication'] == authentication
    assert templates(stored)[0]['headers']['authorization'] == 'Bearer CANARY_XAI_KEY'
    assert 'CANARY_' not in json.dumps(records_for({tid}))


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [None, 1045, 2003])
async def test_sql_capture_keeps_original_login_query_and_actual_result_even_on_connection_failure(capture, monkeypatch, error):
    lab, _ = manager()
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return self
        def execute(self, statement): assert statement == 'SELECT 1'
        def fetchone(self): return (1,)
    def connect(**kwargs):
        assert kwargs['password'] == 'CANARY_SQL_PASSWORD'
        if error: raise pymysql.OperationalError(error, 'Access denied' if error == 1045 else 'Connection unavailable')
        return Connection()
    monkeypatch.setattr(pymysql, 'connect', connect)
    with span('test.revocation'):
        tid = trace_id()
        if error == 2003:
            with pytest.raises(AccessDenied):
                await lab._sql_accepts({'username':'CANARY_SQL_USER','password':'CANARY_SQL_PASSWORD'})
        else:
            assert await lab._sql_accepts({'username':'CANARY_SQL_USER','password':'CANARY_SQL_PASSWORD'}) is (error is None)
    _, stored, sections = captured(tid, 'mysql.query')
    assert sections['connection']['password'] == 'CANARY_SQL_PASSWORD'
    assert sections['query']['statement'] == 'SELECT 1'
    assert sections['query']['executed'] is (error is None)
    assert sections['result'] == ({'row':[1]} if error is None else {
        'error_code': error, 'message': 'Access denied' if error == 1045 else 'Connection unavailable', 'query_executed': False})
    assert templates(stored)[0]['kind'] == 'mysql'
    assert 'CANARY_' not in json.dumps(records_for({tid}))
