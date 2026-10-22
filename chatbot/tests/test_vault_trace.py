import json
import ssl

import httpx
import jwt
import pytest

from app.services import Services, VaultPermissionDenied
from app.telemetry import records_for, span, trace_id
from app.trace_content import ContentRecorder, VAULT_CONTENT_KEYS


@pytest.mark.asyncio
async def test_native_token_revocation_accepts_empty_204(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(204))))
    service = object.__new__(Services)
    service.config = {'vault_addr': 'https://vault.test'}
    service.vault_tls = ssl.create_default_context()
    assert await service.vault_post('auth/token/revoke-self', 'synthetic-native-token', {}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('raw,status', [(True, 200), (True, 403), (False, 200)])
async def test_vault_capture_matches_http_request_and_response(monkeypatch, raw, status):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1' if raw else '0')
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '0')  # independent switch
    token = jwt.encode({'sub': 'test-reader', 'actor-token': {'sub': 'test-agent'},
                        'authorization_details': [{'path': 'database/creds/chatbot-readonly'}]},
                       'canary-test-signing-key-at-least-32-bytes', algorithm='HS256')
    body = {'request_id': 'test-request', 'data': {'username': 'test-user', 'password': 'CANARY_SQL_PASSWORD'}} if status == 200 else {'errors': ['permission denied']}
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(status, json=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    service = object.__new__(Services)
    service.config = {'vault_addr': 'https://vault.test'}
    service.vault_tls = ssl.create_default_context()
    with span('test.vault'):
        tid = trace_id()
        if status == 403:
            with pytest.raises(VaultPermissionDenied):
                await service.vault_get('database/creds/chatbot-readonly', token)
        else:
            assert await service.vault_get('database/creds/chatbot-readonly', token) == body
    record = next(r for r in records_for({tid}) if r['name'] == 'vault.read')
    attrs = record['attributes']
    assert attrs['http.response.status_code'] == status
    assert attrs['vault.capture.raw'] == raw
    if not raw:
        assert not VAULT_CONTENT_KEYS.intersection(attrs)
        assert token not in json.dumps(record) and 'CANARY_SQL_PASSWORD' not in json.dumps(record)
        return
    request = json.loads(attrs['vault.http.request'])
    assert request['url'] == str(sent[0].url)
    assert request['method'] == sent[0].method
    assert request['body'] is None
    for name, value in request['headers'].items():
        assert sent[0].headers[name] == value
    assert json.loads(attrs['vault.auth.jwt']) == sent[0].headers['x-vault-token'] == token
    decoded = json.loads(attrs['vault.auth.jwt.decoded'])
    assert decoded['claims']['sub'] == 'test-reader'
    assert decoded['signature_verified_by_decoder'] is False
    assert json.loads(attrs['vault.http.response'])['body'] == body
    assert all(not attrs[key + '.truncated'] for key in VAULT_CONTENT_KEYS)
    assert record['status'] == ('ERROR' if status == 403 else 'UNSET')


def test_raw_vault_mode_does_not_remove_llm_redaction(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '1')
    token = jwt.encode({'sub': 'test'}, 'canary-test-signing-key-at-least-32-bytes', algorithm='HS256')
    recorder = ContentRecorder()
    with span('test.model.redaction') as current:
        tid = trace_id()
        recorder.capture(current, 'gen_ai.input.messages', {'content': token, 'password': 'CANARY_PASSWORD'})
    encoded = json.dumps(records_for({tid}))
    assert token not in encoded and 'CANARY_PASSWORD' not in encoded
    assert '[REDACTED]' in encoded


@pytest.mark.asyncio
async def test_raw_post_capture_preserves_crypto_payload(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={'data': {'encoded_value': 'opaque-token'}})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    service = object.__new__(Services)
    service.config = {'vault_addr': 'https://vault.test'}
    service.vault_tls = ssl.create_default_context()
    payload = {'value': '12345678Z', 'transformation': 'lumen-dni'}
    with span('test.vault.post'):
        tid = trace_id()
        await service.vault_post('transform/encode/lumen-dni', 'test-token', payload)
    record = next(r for r in records_for({tid}) if r['name'] == 'vault.write')
    request = json.loads(record['attributes']['vault.http.request'])
    assert request['method'] == 'POST'
    assert request['body'] == json.loads(sent[0].content) == payload
