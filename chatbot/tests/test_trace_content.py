import asyncio
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.telemetry import ModelSpans, operation, records_for, span, trace_id
from app.trace_content import ContentRecorder, config_secrets, content_scope


@pytest.mark.asyncio
async def test_model_roundtrip_records_context_tools_results_and_usage(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '1')
    recorder = ContentRecorder(['CANARY_KNOWN_CREDENTIAL'])
    with span('test.content'):
        tid = trace_id()
        callback = ModelSpans('test-model', recorder)
        run_id = uuid4()
        await callback.on_chat_model_start({}, [[
            SystemMessage(content='Instrucciones ' + 'á' * 3000),
            HumanMessage(content='Consulta planes; CANARY_KNOWN_CREDENTIAL'),
            AIMessage(content='', tool_calls=[{'name': 'consultar_planes', 'args': {}, 'id': 'call-1'}]),
            ToolMessage(content=json.dumps({'plans': [{'name': 'Luz Noche'}], 'password': 'CANARY_SQL_SECRET'}),
                        name='consultar_planes', tool_call_id='call-1'),
        ]], run_id=run_id, invocation_params={
            'api_key': 'CANARY_PARAMETER_SECRET', 'max_tokens': 2000,
            'tools': [{'type': 'function', 'function': {'name': 'consultar_planes', 'description': 'Consulta planes',
                                                       'parameters': {'type': 'object', 'properties': {}}}}],
        })
        await callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(
            content='Plan disponible: Luz Noche.', additional_kwargs={'reasoning_content': 'OPAQUE_REASONING'},
            response_metadata={'model_name': 'test-model', 'id': 'response-1', 'finish_reason': 'stop'},
            usage_metadata={'input_tokens': 20, 'output_tokens': 5, 'total_tokens': 25,
                            'input_token_details': {'cache_read': 3}}))]]), run_id=run_id)
    attrs = next(r['attributes'] for r in records_for({tid}) if r['name'] == 'xai.chat')
    inputs = json.loads(attrs['gen_ai.input.messages'])
    assert [m['role'] for m in inputs] == ['system', 'user', 'assistant', 'tool']
    assert inputs[2]['parts'][0]['id'] == inputs[3]['parts'][0]['id'] == 'call-1'
    assert 'Luz Noche' in inputs[3]['parts'][0]['result']
    assert len(attrs['gen_ai.input.messages']) > 2048
    assert not attrs['gen_ai.input.messages.truncated']
    assert json.loads(attrs['gen_ai.tool.definitions'])[0]['name'] == 'consultar_planes'
    assert json.loads(attrs['gen_ai.output.messages'])[0]['finish_reason'] == 'stop'
    assert attrs['lumen.usage.input_token_details.cache_read'] == 3
    assert attrs['gen_ai.response.id'] == 'response-1'
    encoded = json.dumps(records_for({tid}))
    for forbidden in ('CANARY_KNOWN_CREDENTIAL', 'CANARY_SQL_SECRET', 'CANARY_PARAMETER_SECRET', 'OPAQUE_REASONING'):
        assert forbidden not in encoded


def test_redaction_handles_nested_json_and_credential_formats():
    recorder = ContentRecorder(config_secrets({'model': {'api_key': 'KNOWN_PRIVATE_CREDENTIAL'}}))
    data = {'result': {'clientSecret': 'HIDDEN_CLIENT', 'access_token': 'HIDDEN_ACCESS'},
            'nested': '{"password":"HIDDEN_JSON","visible":"Plan 2"}',
            'text': 'KNOWN_PRIVATE_CREDENTIAL Bearer abcdef12345 password="HIDDEN_ASSIGN" '
                    'xai-abcdefghijk tvly-abcdefghijk hvs.abcdefghijk eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1In0.signature '
                    'https://user:password@example.invalid',
            'usage': {'input_tokens': 25}}
    safe = json.dumps(recorder.sanitize(data))
    for forbidden in ('KNOWN_PRIVATE_CREDENTIAL', 'HIDDEN_', 'abcdef', 'eyJ', 'user:password'):
        assert forbidden not in safe
    assert 'Plan 2' in safe and 'input_tokens' in safe


def test_utf8_truncation_is_explicit_and_retains_valid_json(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '1')
    monkeypatch.setenv('LUMEN_TRACE_CONTENT_MAX_BYTES', '1024')
    with span('test.large') as current:
        tid = trace_id()
        ContentRecorder(['HIDDEN_LARGE']).capture(current, 'gen_ai.input.messages', ['á😀HIDDEN_LARGE' * 2000])
    attrs = records_for({tid})[0]['attributes']
    value = attrs['gen_ai.input.messages']
    assert len(value.encode()) <= 1024
    assert attrs['gen_ai.input.messages.truncated']
    assert json.loads(value)['_truncated']
    assert 'HIDDEN_LARGE' not in value


@pytest.mark.asyncio
async def test_content_disabled_excludes_input_output_and_tool_content(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '0')
    with span('test.disabled'):
        tid = trace_id()
        callback = ModelSpans('test-model')
        run_id = uuid4()
        await callback.on_chat_model_start({}, [[HumanMessage(content='PRIVATE_PROMPT')]], run_id=run_id)
        await callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content='PRIVATE_ANSWER'))]]), run_id=run_id)
        @operation('tool.disabled')
        def tool(note):
            return {'note': note}
        with content_scope(callback.recorder):
            tool('PRIVATE_TOOL')
    encoded = json.dumps(records_for({tid}))
    assert 'PRIVATE_' not in encoded
    assert 'gen_ai.input.messages' not in encoded


@pytest.mark.asyncio
async def test_concurrent_tool_capture_keeps_each_sessions_redactor(monkeypatch):
    monkeypatch.setenv('LUMEN_TRACE_CONTENT', '1')
    @operation('tool.test')
    async def tool(note):
        await asyncio.sleep(0)
        return {'note': note, 'password': 'CANARY_DYNAMIC_SQL'}
    async def run(secret, visible):
        with span('test.concurrent'):
            tid = trace_id()
            with content_scope(ContentRecorder([secret])):
                result = await tool(secret + ' ' + visible)
                assert secret in result['note']  # The application result itself is never modified.
        return tid
    ids = await asyncio.gather(run('SESSION_SECRET_A', 'VISIBLE_A'), run('SESSION_SECRET_B', 'VISIBLE_B'))
    for i, tid in enumerate(ids):
        encoded = json.dumps(records_for({tid}))
        assert 'SESSION_SECRET_' not in encoded and 'CANARY_DYNAMIC_SQL' not in encoded
        assert ('VISIBLE_A' if i == 0 else 'VISIBLE_B') in encoded
        assert ('VISIBLE_B' if i == 0 else 'VISIBLE_A') not in encoded
