"""Inbox trace links must follow the action the user just performed."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing.user_simulation import user_simulation

from app.application_ui import render_applications
from app.applications import DEMO_FORM
from app.security import Session
from app.services import VaultPermissionDenied


@pytest.mark.asyncio
@pytest.mark.parametrize('denied', [False, True])
async def test_inbox_trace_follows_reveal_including_vault_denial(denied):
    session = Session('ui-test', subject='supervisor', name='Supervisor')
    services = SimpleNamespace(
        role=lambda _: 'readonly', can_reveal=lambda _: True,
        contracts=SimpleNamespace(config={}),
        applications=AsyncMock(return_value=[{
            'application_id': 'example', 'plan_name': 'Luz Noche', 'status': 'borrador',
            'created_at': '2026-10-22', 'dni_hint': '***', 'iban_hint': 'ES***',
        }]),
        reveal_application=AsyncMock(return_value=DEMO_FORM),
    )
    if denied:
        services.reveal_application.side_effect = VaultPermissionDenied('denied')

    async def run_action(name, action):
        session.traces.append('a' * 32 if name.endswith('.list') else 'b' * 32)
        return await action()

    async def page():
        await render_applications(services, session, lambda: None, run_action, 'es')

    async with user_simulation(page) as user:
        await user.open('/')
        await user.should_see('Ver última traza')
        link = next(iter(user.find('Ver última traza', kind=ui.link).elements))
        assert link.props['href'] == '/traces/' + 'a' * 32
        user.find('Revelar datos', kind=ui.button).click()
        await user.should_see('Estos datos requieren otro permiso.' if denied else 'Datos de la solicitud')
        assert link.props['href'] == '/traces/' + 'b' * 32
        services.reveal_application.assert_awaited_once_with(session, 'example')


@pytest.mark.asyncio
@pytest.mark.parametrize('download_ok', [False, True])
async def test_inbox_trace_follows_pdf_endpoint(monkeypatch, download_ok):
    from app import contracts_ui
    from test_contracts import setup
    manager, session, item = setup()
    services = manager.services
    services.contracts = manager
    services.can_reveal = lambda _: False
    services.applications = AsyncMock(return_value=[{
        'application_id': item.application_id, 'subject_id': session.subject,
        'plan_name': 'Luz Noche', 'status': 'contratada', 'created_at': '2026-10-22',
        'dni_hint': '***', 'iban_hint': 'ES***', 'contract_id': item.id,
    }])

    completed = asyncio.Event()

    async def downloaded(*args):
        # The authenticated PDF endpoint creates its own trace, outside run_action.
        session.traces.append('d' * 32)
        asyncio.get_running_loop().call_soon(completed.set)
        return download_ok
    monkeypatch.setattr(contracts_ui, 'download_contract', downloaded)

    async def run_action(name, action):
        session.traces.append('a' * 32)
        return await action()

    async def page():
        await render_applications(services, session, lambda: None, run_action, 'es')

    async with user_simulation(page) as user:
        await user.open('/')
        await user.should_see('Descargar contrato PDF')
        user.find('Descargar contrato PDF', kind=ui.button).click()
        await user.should_see('Descargar contrato PDF')
        # call_soon runs after the download callback and its finally block.
        await asyncio.wait_for(completed.wait(), timeout=2)
        link = next(iter(user.find('Ver última traza', kind=ui.link).elements))
        assert link.props['href'] == '/traces/' + 'd' * 32
