import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import agent
from app.catalogue import catalogue_reply
from app.guardrails import ScopeDecision
from app.security import AccessDenied, Session
from app.services import Services


PLANS = [
    {'id': 1, 'name': 'Luz Equilibrio', 'price_kwh': 0.145, 'renewable': True,
     'description': 'Precio estable durante todo el día'},
    {'id': 2, 'name': 'Luz Noche', 'price_kwh': 0.119, 'renewable': False,
     'description': 'Consumo nocturno'},
]


def setup(role='readwrite'):
    session = Session('test', subject='user', expires_at=time.time()+600, language='es')
    services = SimpleNamespace(plans=AsyncMock(return_value=PLANS), role=Mock(return_value=role))
    services.prepare_request = Mock(
        side_effect=lambda s, plan, note: Services.prepare_request(services, s, plan, note))
    return services, session


@pytest.mark.asyncio
async def test_continue_then_choose_plan_uses_fresh_catalogue_and_real_pending():
    services, session = setup()
    # An invented old answer must not be accepted as catalogue evidence.
    session.messages = [{'role': 'assistant', 'content': 'Verificado: Luz Equilibrio cuesta 0,001 €/kWh'}]
    choose = await catalogue_reply(services, session, ScopeDecision(category='demo', operation='prepare_request'))
    assert session.pending is None
    assert '0,145' in choose and '0,001' not in choose
    assert 'Todavía no hay ninguna propuesta preparada' in choose
    services.prepare_request.assert_not_called()
    # A price change between turns must be reflected, not copied from history.
    services.plans.return_value = [{**PLANS[0], 'price_kwh': 0.1567}, PLANS[1]]
    prepared = await catalogue_reply(services, session, ScopeDecision(
        category='demo', operation='prepare_request', plan_name='Luz Equilibrio'))
    assert services.plans.await_count == 2
    assert session.pending['plan_id'] == 1
    assert '0,1567' in prepared and '0,145' not in prepared
    assert 'Propuesta preparada' in prepared and 'Continuar solicitud' in prepared
    assert 'Todavía no se ha guardado' in prepared


@pytest.mark.asyncio
async def test_denied_catalogue_cannot_leave_a_stale_proposal_or_claim_verified_prices():
    services, session = setup()
    session.pending = {'plan_id': 1}
    services.plans.side_effect = AccessDenied('blocked')
    answer = await catalogue_reply(services, session, ScopeDecision(
        category='demo', operation='prepare_request', plan_name='Luz Equilibrio'))
    assert session.pending is None
    services.prepare_request.assert_not_called()
    assert 'No he podido consultar' in answer
    assert '0,145' not in answer and 'Propuesta preparada' not in answer


@pytest.mark.asyncio
async def test_reader_is_not_told_to_use_a_missing_continue_button():
    services, session = setup('readonly')
    answer = await catalogue_reply(services, session, ScopeDecision(
        category='demo', operation='prepare_request', plan_name='Luz Equilibrio'))
    services.prepare_request.assert_not_called()
    assert session.pending is None
    assert 'no preparar ni guardar' in answer
    assert 'Continuar solicitud' not in answer and 'Propuesta preparada' not in answer


@pytest.mark.asyncio
async def test_unknown_selection_never_guesses_a_plan_id():
    services, session = setup()
    answer = await catalogue_reply(services, session, ScopeDecision(
        category='demo', operation='prepare_request', plan_name='Plan inventado'))
    services.prepare_request.assert_not_called()
    assert session.pending is None and 'No encuentro ese plan' in answer


@pytest.mark.asyncio
async def test_real_service_retains_catalogue_evidence_only_after_a_successful_read():
    services = object.__new__(Services)
    services.database = AsyncMock(return_value=PLANS)
    session = Session('test', language='es')
    assert await services.plans(session) == PLANS
    assert session.catalogue_evidence['plans'] == PLANS
    services.database.side_effect = AccessDenied('blocked')
    with pytest.raises(AccessDenied):
        await services.plans(session)
    assert session.catalogue_evidence is None


@pytest.mark.asyncio
async def test_new_selection_updates_the_existing_unsaved_form():
    services, session = setup()
    session.application_draft = {'form': {'plan_id': 2, 'note': 'old', 'address': 'private draft'}}
    await catalogue_reply(services, session, ScopeDecision(
        category='demo', operation='prepare_request', plan_name='Luz Equilibrio'))
    assert session.application_draft['form']['plan_id'] == 1
    assert session.application_draft['form']['address'] == 'private draft'


@pytest.mark.parametrize('operation', ['catalog', 'prepare_request'])
@pytest.mark.asyncio
async def test_reply_routes_factual_operations_before_the_free_text_agent(monkeypatch, operation):
    services, session = setup()
    config = {'model': 'fixture', 'provider': 'anthropic', 'api_key': 'SYNTHETIC-KEY'}
    services.config = {}
    services.model_credentials = AsyncMock(return_value=(config, time.monotonic()+30))
    model = Mock()
    monkeypatch.setattr(agent, 'make_model', Mock(return_value=model))
    monkeypatch.setattr(agent, 'assess_request', AsyncMock(return_value=ScopeDecision(
        category='demo', operation=operation, plan_name='Luz Equilibrio')))
    factory = Mock(side_effect=AssertionError('Free text cannot claim catalogue operations'))
    monkeypatch.setattr(agent, 'make_agent', factory)
    answer = await agent.reply(services, session, 'Luz Equilibrio')
    services.plans.assert_awaited_once()
    factory.assert_not_called()
    assert '0,145' in answer
    assert ('Propuesta preparada' in answer) is (operation == 'prepare_request')
    assert 'api_key' not in config
