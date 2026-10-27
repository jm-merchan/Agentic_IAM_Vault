import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from app.i18n import EN, Translator, browser_language, request_language, safe_return_path
from app.catalogue import catalogue_reply
from app.guardrails import OUT_OF_SCOPE, ScopeDecision, repeats_blocked_request
from app.security import Session
from app.trace_flow import build_flow
from app.trace_flow_ui import localize_flow
from app.trace_inspection import localize_inspection


@pytest.mark.parametrize('header,expected', [
    ('es-ES,es;q=0.9,en;q=0.8', 'es'), ('en-GB,en;q=0.9,es;q=0.8', 'en'),
    ('es;q=0.2,en-US;q=0.9', 'en'), ('fr-FR,es-MX;q=0.8,en;q=0.6', 'es'),
    ('fr-FR', 'en'), ('', 'en'), ('es;q=0,en;q=0.5', 'en'),
    ('es;q=broken,en-US', 'en'), ('es;q=2,en;q=0.8', 'en'),
])
def test_browser_language_respects_regions_and_weights(header, expected):
    assert browser_language(header) == expected


def test_explicit_choice_takes_precedence_and_requests_are_isolated():
    def req(browser, cookie=''):
        return Request({'type': 'http', 'headers': [(b'accept-language', browser.encode()), (b'cookie', cookie.encode())]})
    assert request_language(req('en-US', 'lumen_language=es')) == 'es'
    assert request_language(req('es-ES', 'lumen_language=en')) == 'en'
    assert request_language(req('es-MX', 'lumen_language=invalid')) == 'es'
    assert request_language(req('en-US')) == 'en'
    assert request_language(req('es-ES')) == 'es'


@pytest.mark.parametrize('path', ['https://example.org', '//example.org', '/\\example.org', '/auth/logout', '/traces/' + 'a'*32 + '/steps/123/sensitive', '/?x=1', '/solicitud\r\nX-Test:x'])
def test_switch_cannot_redirect_outside_supported_pages(path):
    assert safe_return_path(path) == '/'


@pytest.mark.parametrize('path', ['/', '/solicitud', '/solicitudes', '/traces/' + 'a'*32,
                                '/traces/' + 'a'*32 + '?span=' + 'b'*16])
def test_switch_keeps_current_page(path):
    assert safe_return_path(path) == path


@pytest.mark.parametrize('suffix', ['?span=https://example.org', '?span=' + 'b'*16 + '&next=https://example.org', '?span=' + 'b'*15])
def test_trace_switch_rejects_unexpected_query(suffix):
    assert safe_return_path('/traces/' + 'a'*32 + suffix) == '/'


@pytest.mark.asyncio
async def test_language_button_keeps_linked_trace_step(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from nicegui import ui
    from nicegui.testing.user_simulation import user_simulation
    from app.i18n import language_switch

    path = '/traces/' + 'a'*32
    request = Request({'type': 'http', 'path': path, 'query_string': b'span=' + b'b'*16, 'headers': []})
    navigate = Mock()
    async with user_simulation(lambda: language_switch(request, Translator('es'))) as user:
        await user.open('/')
        monkeypatch.setattr(ui.navigate, 'to', navigate)
        user.find('EN', kind=ui.button).click()
        target = navigate.call_args.args[0]
        assert urlsplit(target).path == '/language/en'
        assert parse_qs(urlsplit(target).query)['next'] == [path + '?span=' + 'b'*16]


def test_translations_and_placeholders_never_modify_inserted_values():
    es, en = Translator('es'), Translator('en')
    assert es('Continuar solicitud') == 'Continuar solicitud'
    assert en('Continuar solicitud') == 'Continue application'
    assert en('Referencia · abc') == 'Reference · abc'
    value = 'Solicitud guardada {token}'
    assert en('Solicitud de {plan}', plan=value) == 'Application for ' + value
    assert es.number(0.145) == '0,145'
    assert en.number(0.145) == '0.145'
    assert en.props('flat aria-label="Cambiar tema"') == 'flat aria-label="Switch theme"'


@pytest.mark.asyncio
async def test_vault_denial_is_fully_translated(monkeypatch):
    import httpx
    from app import services as services_module
    from app.services import Services, VaultPermissionDenied
    services = Services.__new__(Services)
    services.config = {'vault_addr': 'https://vault.test'}
    services.vault_tls = True
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={'errors': ['permission denied']}))
    client = httpx.AsyncClient
    monkeypatch.setattr(services_module.httpx, 'AsyncClient',
                        lambda **kwargs: client(transport=transport, **{k: v for k, v in kwargs.items() if k != 'verify'}))
    with pytest.raises(VaultPermissionDenied) as denied:
        await services.vault_get('transit/decrypt/lumen-applications', 'token')
    message = Translator('en')(str(denied.value))
    assert message == ('Vault denied this operation (HTTP 403): transit/decrypt/lumen-applications. '
                       'Check the permissions or active access blocks.')


@pytest.mark.asyncio
async def test_catalogue_in_english_keeps_real_prices_permissions_and_proposal_state():
    session = Session('test', subject='writer', expires_at=time.time()+600)
    plans = [{'id': 1, 'name': 'Luz Equilibrio', 'price_kwh': 0.145, 'renewable': True,
              'description': 'Precio estable durante todo el día'}]
    service = SimpleNamespace(plans=AsyncMock(return_value=plans), role=Mock(return_value='readwrite'))
    def prepare(s, plan, note): s.pending = {'plan_id': plan, 'note': note}
    service.prepare_request = Mock(side_effect=prepare)
    decision = ScopeDecision(category='demo', operation='prepare_request', plan_name='Luz Equilibrio')
    answer = await catalogue_reply(service, session, decision, language='en')
    assert 'Proposal prepared: Luz Equilibrio' in answer
    assert '0.145 €/kWh' in answer and 'Renewable energy: Yes' in answer
    assert 'Continue application' in answer and 'No application has been saved yet' in answer
    assert session.pending['plan_id'] == 1
    assert plans[0]['description'] == 'Precio estable durante todo el día'
    service.role.return_value = 'readonly'
    assert 'not prepare or save' in await catalogue_reply(service, session, decision, language='en')
    assert session.pending is None


@pytest.mark.parametrize('language', ['es', 'en'])
@pytest.mark.parametrize('followup', ['continúa', 'go ahead', 'continue', 'sí'])
def test_blocked_followups_stay_blocked_across_language_changes(language, followup):
    history = [{'role': 'assistant', 'content': Translator(language)(OUT_OF_SCOPE)}]
    assert repeats_blocked_request(history, followup)
    assert not repeats_blocked_request(history, 'How can I save energy?')


def test_model_uses_selected_language_instead_of_old_history(monkeypatch):
    from app import agent
    factory = Mock()
    monkeypatch.setattr(agent, 'create_deep_agent', factory)
    session = Session('test', language='es', messages=[{'role': 'assistant', 'content': 'Hola'}])
    services = SimpleNamespace(config={}, role=lambda s: 'readonly')
    agent.make_agent(services, session, config={'model': 'test', 'provider': 'openai'}, model=object(), language='en')
    prompt = factory.call_args.kwargs['system_prompt']
    assert prompt.startswith('Reply in English')
    assert 'Continue application' in prompt and 'Save draft' in prompt
    assert 'Habla en español' not in prompt
    assert session.language == 'es'  # Page preference cannot mutate another tab's locale.


def test_trace_localization_preserves_technical_evidence():
    records = [{'name': 'vault.read', 'span_id': 'a', 'trace_id': 't', 'parent_id': None,
                'start_ns': 0, 'end_ns': 1000000, 'duration_ms': 1, 'status': 'UNSET',
                'attributes': {'vault.path': 'database/creds/chatbot-readonly', 'http.response.status_code': 200}}]
    original = build_flow(records)
    localized = localize_flow(original, 'en')
    assert localized['calls'][0]['title'] == 'Get MySQL credentials'
    assert original['calls'][0]['title'] == 'Obtener credenciales de MySQL'
    for field in ('id', 'name', 'method', 'endpoint', 'request_id', 'duration_ms', 'context'):
        assert original['calls'][0].get(field) == localized['calls'][0].get(field)
    body = {'message': 'Paso no disponible en esta traza.', 'sections': [
        {'key': 'authentication', 'title': 'Autenticación HTTP Basic',
         'value': {'client_secret': 'Solicitud guardada', 'Authorization': 'Basic TEST', 'plaintext': 'Hola'}}]}
    before = deepcopy(body)
    localized = localize_inspection(body, Translator('en'))
    assert localized['sections'][0]['title'] == 'HTTP Basic authentication'
    assert localized['sections'][0]['value'] == before['sections'][0]['value']
    assert body == before


def test_catalogue_templates_have_matching_placeholders():
    from string import Formatter
    for source, target in EN.items():
        fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
        assert fields(source) == fields(target), source
