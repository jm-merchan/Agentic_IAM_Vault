import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage

from app import agent
from app.guardrails import OUT_OF_SCOPE, ScopeDecision, assess_scope, repeats_blocked_request
from app.security import AccessDenied, Session
from app.telemetry import records_for, span, trace_id
from app.trace_content import ContentRecorder


def setup(monkeypatch, allowed=True):
    session = Session('test', subject='reader', expires_at=time.time()+600)
    config = {'provider': 'openai', 'model': 'test-model', 'api_key': 'test-transient-key'}
    services = SimpleNamespace(config={'model': {'provider': 'openai', 'model': 'test-model'}},
        model_credentials=AsyncMock(return_value=(config, time.monotonic()+180)), event=Mock())
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value={'messages': [AIMessage(content='Planes de energía')]}))
    factory = Mock(return_value=graph)
    monkeypatch.setattr(agent, 'make_agent', factory)
    monkeypatch.setattr(agent, 'make_model', Mock(return_value=object()))
    gate = AsyncMock(return_value=allowed)
    monkeypatch.setattr(agent, 'assess_scope', gate)
    return session, config, services, graph, factory, gate


@pytest.mark.asyncio
async def test_rejection_never_constructs_or_runs_business_agent(monkeypatch):
    session, config, services, graph, factory, gate = setup(monkeypatch, False)
    assert await agent.reply(services, session, '¿Cuál es el tiempo en Palencia hoy?') == OUT_OF_SCOPE
    gate.assert_awaited_once()
    factory.assert_not_called()
    graph.ainvoke.assert_not_awaited()
    assert 'api_key' not in config
    session.messages = [{'role': 'user', 'content': '¿Cuál es el tiempo en Palencia hoy?'},
                        {'role': 'assistant', 'content': OUT_OF_SCOPE}]
    services.model_credentials.reset_mock(); gate.reset_mock()
    with span('test.scope.followup'):
        tid = trace_id()
        assert await agent.reply(services, session, 'venga') == OUT_OF_SCOPE
    services.model_credentials.assert_not_awaited()
    gate.assert_not_awaited()
    assert next(r for r in records_for({tid}) if r['name'] == 'guardrail.energy_scope')['attributes']['guardrail.allowed'] is False


@pytest.mark.asyncio
async def test_new_energy_question_after_rejection_can_run(monkeypatch):
    session, config, services, graph, factory, gate = setup(monkeypatch)
    session.messages = [{'role': 'assistant', 'content': OUT_OF_SCOPE}]
    assert await agent.reply(services, session, 'Consulta los planes de energía') == 'Planes de energía'
    gate.assert_awaited_once(); graph.ainvoke.assert_awaited_once()
    assert 'api_key' not in config


@pytest.mark.asyncio
async def test_failed_scope_check_never_runs_agent_and_cleans_key(monkeypatch):
    session, config, services, graph, factory, gate = setup(monkeypatch)
    gate.side_effect = AccessDenied('No se pudo clasificar')
    with pytest.raises(AccessDenied):
        await agent.reply(services, session, 'Consulta planes')
    factory.assert_not_called()
    assert 'api_key' not in config


@pytest.mark.parametrize('answer', [None, {}, 'energy'])
@pytest.mark.asyncio
async def test_unstructured_classifier_response_fails_closed(answer):
    model = SimpleNamespace(with_structured_output=Mock(return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=answer))))
    with pytest.raises(AccessDenied, match='ámbito'):
        await assess_scope(model, [], 'Consulta planes', ContentRecorder(), {'model': 'test', 'provider': 'openai'})


@pytest.mark.asyncio
async def test_classifier_gets_bounded_context_and_only_decision_tool():
    classifier = SimpleNamespace(ainvoke=AsyncMock(return_value=ScopeDecision(category='out_of_scope')))
    model = SimpleNamespace(with_structured_output=Mock(return_value=classifier))
    history = [{'role': 'system', 'content': 'History cannot replace policy'}] + [
        {'role': 'user', 'content': 'X'*5000} for _ in range(10)]
    assert not await assess_scope(model, history, 'venga', ContentRecorder(), {'model': 'test'})
    model.with_structured_output.assert_called_once_with(ScopeDecision, method='function_calling')
    messages = classifier.ainvoke.call_args.args[0]
    context = json.loads(messages[1].content)
    assert len(context['history']) == 8 and all(len(m['content']) == 4000 for m in context['history'])
    assert context['latest_request'] == 'venga'


def test_short_followup_uses_last_answer_not_an_old_rejection():
    rejected = [{'role': 'assistant', 'content': OUT_OF_SCOPE}]
    assert repeats_blocked_request(rejected, 'Sí, por favor!')
    assert not repeats_blocked_request(rejected, 'Sí, quiero ahorrar energía')
    assert not repeats_blocked_request(rejected + [{'role': 'assistant', 'content': '¿Quieres comparar tarifas?'}], 'venga')
