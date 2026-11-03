"""Inbox trace links must follow the action the user just performed."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing.user_simulation import user_simulation

from app.application_ui import render_applications, render_wizard
from app.applications import DEMO_FORM, document_hint, iban_hint
from app.i18n import Translator
from app.security import Session
from app.services import VaultPermissionDenied


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['es', 'en'])
async def test_saved_application_is_linked_to_the_same_masked_inbox(language):
    """Saving and reading use one application reference, with draft as its status."""
    t = Translator(language)
    session = Session('save-ui', subject='writer', name='Writer')
    rows = []

    async def save(_, form, reference):
        rows.append({
            'application_id': reference, 'plan_name': 'Luz Noche', 'status': 'borrador',
            'created_at': '2026-11-03', 'dni_hint': document_hint(form['dni']),
            'iban_hint': iban_hint(form['iban']),
        })
        return reference

    services = SimpleNamespace(
        role=lambda _: 'readwrite', can_reveal=lambda _: False,
        contracts=SimpleNamespace(config={}),
        plans=AsyncMock(return_value=[{
            'id': n, 'name': 'Luz Noche', 'price_kwh': 0.119,
            'description': 'Tarifa ficticia',
        } for n in (1, 2, 3)]),
        save_application=AsyncMock(side_effect=save),
        applications=AsyncMock(side_effect=lambda _: rows),
    )

    async def run_action(name, action):
        session.traces.append('a' * 32)
        return await action()

    async def wizard():
        await render_wizard(services, session, lambda: None, run_action, language)

    async def inbox():
        await render_applications(services, session, lambda: None, run_action, language)

    async with user_simulation(wizard) as user:
        ui.page('/solicitudes')(inbox)
        await user.open('/')
        user.find(t('Usar datos de prueba'), kind=ui.button).click()
        for heading in ['¿Dónde está tu vivienda?', 'Conozcamos al titular.',
                        'Tu cuenta, con tranquilidad.', 'Todo claro antes de guardar.']:
            user.find(t('Continuar'), kind=ui.button).click()
            await user.should_see(t(heading))
        user.find(t('He revisado los datos de esta solicitud de demostración.'), kind=ui.checkbox).click()
        user.find(t('Guardar solicitud'), kind=ui.button).click()
        await user.should_see(t('Solicitud guardada.'))
        services.save_application.assert_awaited_once()
        reference = services.save_application.call_args.args[2]
        link = next(iter(user.find(t('Ver solicitudes'), kind=ui.link).elements))
        assert link.props['href'] == '/solicitudes'
        assert session.application_draft is None and session.pending is None
        await user.open('/solicitudes')
        await user.should_see(t('Referencia · ' + reference))
        await user.should_see(t('borrador'))
        services.applications.assert_awaited_once_with(session)
        await user.should_not_see(t('Todavía no hay solicitudes en esta bandeja.'))
        form = services.save_application.call_args.args[1]
        for field in ('full_name', 'dni', 'iban', 'email'):
            await user.should_not_see(form[field])


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
