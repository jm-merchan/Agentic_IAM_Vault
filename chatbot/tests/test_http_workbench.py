import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import lab_capture
from app.agent import CapturedChatOpenAI, CapturedChatXAI
from app.anthropic_model import FederatedChatAnthropic
from app.http_capture import model_http_client, close_model_http
from app.request_workbench import templates, workbench_router, execute_http, validate_http
from app.security import Session
from app.telemetry import ModelSpans, span, trace_id, records_for


@pytest.fixture(autouse=True)
def lab(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '1')
    monkeypatch.setattr(lab_capture, 'STORE', lab_capture.CaptureStore())


def chat_response(provider, content='Respuesta'):
    if provider == 'anthropic':
        return {'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'model': 'claude-test',
                'content': [{'type': 'text', 'text': content}], 'stop_reason': 'end_turn',
                'usage': {'input_tokens': 4, 'output_tokens': 2}}
    return {'id': 'chat-test', 'object': 'chat.completion', 'model': 'test',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 4, 'completion_tokens': 2, 'total_tokens': 6}}


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['openai', 'xai', 'anthropic'])
async def test_actual_sdk_payload_tools_and_retry_are_bound_to_model_span(provider, monkeypatch):
    from app import anthropic_model
    requests = []
    http = httpx2 if provider == 'anthropic' else httpx
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return http.Response(429, headers={'retry-after-ms': '1'}, json={'error': {'message': 'retry', 'type': 'rate_limit_error'}})
        return http.Response(200, json=chat_response(provider))
    client = model_http_client(http_module=http, transport=http.MockTransport(handler))
    if provider == 'anthropic':
        monkeypatch.setattr(anthropic_model, 'model_http_client', lambda **kw: client)
        model = FederatedChatAnthropic(model='claude-test', api_key='CANARY_MODEL', max_retries=1)
    else:
        cls = CapturedChatOpenAI if provider == 'openai' else CapturedChatXAI
        model = cls(model='grok-test' if provider == 'xai' else 'gpt-test', api_key='CANARY_MODEL',
                    http_async_client=client, max_retries=1)
    tool = {'type': 'function', 'function': {'name': 'catalogue', 'description': 'Read plans',
                                            'parameters': {'type': 'object', 'properties': {}}}}
    with span('test.model'):
        tid = trace_id()
        callbacks = ModelSpans('test', provider=provider, credential='CANARY_MODEL')
        result = await model.bind_tools([tool]).ainvoke([('system', 'SYSTEM_CANARY'), ('human', 'USER_CANARY')],
                                                       config={'callbacks': [callbacks]})
    assert result.content
    record = next(r for r in records_for({tid}) if r['name'] == provider + '.chat')
    stored = lab_capture.STORE.get(tid, record['span_id'])
    actual = templates(stored)
    assert len(actual) == 2
    for index, item in enumerate(actual):
        assert item['body'].encode() == requests[index].content
        body = json.loads(item['body'])
        assert 'SYSTEM_CANARY' in item['body'] and 'USER_CANARY' in item['body']
        assert body['tools']
        assert item['headers']['authorization'] == 'Bearer CANARY_MODEL'
        if provider == 'anthropic':
            assert 'x-api-key' not in item['headers']
    assert record['attributes']['lumen.http.attempts'] == 2
    assert 'CANARY_MODEL' not in json.dumps(records_for({tid}))
    await close_model_http(model)
    assert client.is_closed


@pytest.mark.asyncio
async def test_parallel_model_calls_do_not_mix_credentials_or_messages():
    async def handler(request):
        await asyncio.sleep(.01)
        return httpx.Response(200, json=chat_response('openai'))
    async def run(word):
        model = CapturedChatOpenAI(model='gpt-test', api_key=word, http_async_client=model_http_client(transport=httpx.MockTransport(handler)))
        with span('test.parallel'):
            tid = trace_id()
            await model.ainvoke(word, config={'callbacks': [ModelSpans('test', provider='openai', credential=word)]})
        record = next(r for r in records_for({tid}) if r['name'] == 'openai.chat')
        item = templates(lab_capture.STORE.get(tid, record['span_id']))[0]
        assert item['headers']['authorization'] == 'Bearer ' + word
        assert json.loads(item['body'])['messages'][0]['content'] == word
        await close_model_http(model)
    await asyncio.gather(run('ONE_CANARY'), run('TWO_CANARY'))


@pytest.mark.asyncio
async def test_stream_capture_does_not_consume_or_change_sdk_stream():
    events = [dict(id='chat-test', object='chat.completion.chunk', model='gpt-test',
                   choices=[dict(index=0, delta={'role': 'assistant', 'content': text}, finish_reason=None)])
              for text in ['Hola ', 'mundo']]
    payload = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events) + 'data: [DONE]\n\n'
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in [payload[:25], payload[25:]]:
                yield chunk.encode()
    def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks())
    model = CapturedChatOpenAI(model='gpt-test', api_key='STREAM_CANARY',
                              http_async_client=model_http_client(transport=httpx.MockTransport(handler)))
    with span('test.stream'):
        tid = trace_id()
        parts = [part.content async for part in model.astream('Pregunta', config={'callbacks': [ModelSpans('test', provider='openai')]})]
    assert ''.join(parts) == 'Hola mundo'
    record = next(r for r in records_for({tid}) if r['name'] == 'openai.chat')
    stored = lab_capture.STORE.get(tid, record['span_id'])
    assert stored['sections']['http.response.1']['value']['body_text'] == payload
    await close_model_http(model)


@pytest.fixture
def workbench(monkeypatch):
    from app import request_workbench
    tid, sid = 'a' * 32, 'b' * 16
    session = Session('owner', subject='user', expires_at=time.time() + 600)
    session.traces.append(tid)
    identity = SimpleNamespace(sessions={'owner': session, 'other': Session('other', subject='other', expires_at=time.time()+600)})
    lab_capture.STORE.put(tid, sid, 'http.request.1', 'HTTP', dict(method='POST', url='https://verify.example/oauth/token',
                         headers={'authorization': 'Basic CANARY', 'content-type': 'application/x-www-form-urlencoded'},
                         body_text='grant_type=client_credentials&scope=a%20b', attempt=1))
    app = FastAPI()
    app.include_router(workbench_router(identity, lambda ids: [dict(trace_id=tid, span_id=sid)]))
    client = TestClient(app)
    client.cookies.set('lumen_session', 'owner')
    client.headers['Origin'] = 'http://testserver'
    sent = []
    async def execute(template, data, **kw):
        sent.append(validate_http(template, data))
        return dict(kind='http', status_code=401, body='expired', headers={})
    monkeypatch.setattr(request_workbench, 'execute_http', execute)
    data = dict(template_id='http.request.1', method='POST', url='https://verify.example/oauth/token',
                headers={'authorization': 'Basic CANARY', 'content-type': 'application/x-www-form-urlencoded'},
                body='grant_type=client_credentials&scope=a%20b')
    return client, f'/traces/{tid}/steps/{sid}/replay', data, sent, session


def test_replay_uses_explicit_payload_once_and_returns_actual_failure(workbench):
    client, url, data, sent, _ = workbench
    assert client.get(url).status_code == 405 and not sent
    result = client.post(url, json=data)
    assert result.status_code == 200 and result.json()['status_code'] == 401
    assert result.headers['cache-control'] == 'no-store'
    assert sent == [('POST', data['url'], data['headers'], data['body'].encode())]


@pytest.mark.parametrize('change', ['owner', 'expired_session', 'origin', 'no_origin', 'fetch_site', 'mode', 'expired_capture', 'truncated'])
def test_replay_denied_before_execution(workbench, monkeypatch, change):
    client, url, data, sent, session = workbench
    if change == 'owner': client.cookies.set('lumen_session', 'other')
    if change == 'expired_session': session.expires_at = 0
    if change == 'origin': client.headers['Origin'] = 'https://evil.example'
    if change == 'no_origin': del client.headers['Origin']
    if change == 'fetch_site': client.headers['Sec-Fetch-Site'] = 'cross-site'
    if change == 'mode': monkeypatch.setenv('LUMEN_TRACE_VAULT_RAW', '0')
    if change == 'expired_capture': lab_capture.STORE.entries.clear()
    if change == 'truncated': next(iter(lab_capture.STORE.entries.values()))['sections']['http.request.1']['truncated'] = True
    assert client.post(url, json=data).status_code in {403, 404, 410}
    assert not sent


@pytest.mark.parametrize('target', ['https://evil.example/', 'http://verify.example/', 'https://verify.example:444/',
                                    'https://name:pass@verify.example/', 'file:///tmp/test', 'https://verify.example/#fragment'])
def test_replay_cannot_forward_captured_token_to_other_origin(workbench, target):
    client, url, data, sent, _ = workbench
    data['url'] = target
    assert client.post(url, json=data).status_code == 400
    assert not sent


@pytest.mark.asyncio
async def test_transport_does_not_follow_redirects_or_refresh_and_keeps_utf8(monkeypatch):
    from app import request_workbench
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(302, headers={'location': 'https://elsewhere.example', 'set-cookie': 'opaque=1'}, text='redirect')
    original = httpx.AsyncClient
    def client(**kw):
        assert kw['follow_redirects'] is False and kw['trust_env'] is False
        return original(**kw, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(request_workbench.httpx, 'AsyncClient', client)
    result = await execute_http({'url': 'https://api.example/path'}, dict(method='POST', url='https://api.example/path',
                headers={'authorization': 'Bearer EXACT_CANARY', 'host': 'evil', 'content-length': '0'}, body='{"question":"energía"}'))
    assert result['status_code'] == 302 and len(sent) == 1
    assert sent[0].content == '{"question":"energía"}'.encode()
    assert sent[0].headers['authorization'] == 'Bearer EXACT_CANARY'
    assert sent[0].headers['host'] == 'api.example'
    assert int(sent[0].headers['content-length']) == len(sent[0].content)


def test_mysql_uses_captured_connection_and_sql_parameters(monkeypatch):
    from app import request_workbench
    from unittest.mock import MagicMock
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.description = ('column',)
    cursor.fetchmany.return_value = [{'plan': 'demo'}]
    cursor.rowcount = 1
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(request_workbench.pymysql, 'connect', connect)
    result = request_workbench.execute_sql({'connection': dict(host='127.0.0.1', port=13306, database='scripting', username='leased', password='DYNAMIC_CANARY')},
        {'statement': 'SELECT * FROM plans WHERE id=%s', 'parameters': [2], 'host': 'untrusted'})
    assert connect.call_args.kwargs['host'] == '127.0.0.1'
    assert connect.call_args.kwargs['password'] == 'DYNAMIC_CANARY'
    cursor.execute.assert_called_once_with('SELECT * FROM plans WHERE id=%s', [2])
    conn.commit.assert_called_once()
    assert result['rows'] == [{'plan': 'demo'}]
