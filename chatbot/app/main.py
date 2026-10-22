from __future__ import annotations

import asyncio
import json
import os
import logging
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse, HTMLResponse
from nicegui import app, ui

from .i18n import LANGUAGE_COOKIE, Translator, request_language, safe_return_path, page_language, language_switch
from .catalogue import table
from .agent import reply
from .model_config import PROVIDER_LABELS, model_profiles, select_provider
from .security import AccessDenied, Identity, load_config, role_for_groups
from .services import Services
from .telemetry import records_for, span, trace_id
from .trace_content import CONTENT_KEYS, VAULT_CONTENT_KEYS, SPIFFE_CONTENT_KEYS
from .trace_inspection import inspection_router
from .request_workbench import workbench_router
from .contracts_http import contract_download_router
from .trace_links import grafana_trace_url
from .trace_flow_ui import TraceFlow
from .live_call_flow_ui import lab_http_badge, mount_live_call_flow
from .application_ui import render_wizard, render_applications
from .task_agents import actor_credential, task_agents_ready, task_allows
from .task_agent_ui import task_agent_selector
from .rar_lab_ui import render_rar_lab
from .personal_spaces_ui import render_personal_spaces

CONFIG = load_config()
IDENTITY = Identity(CONFIG)
SERVICES = Services(CONFIG, IDENTITY)
app.on_startup(SERVICES.agent_inspector.start)
app.on_shutdown(SERVICES.agent_inspector.close)
app.timer(60, SERVICES.contracts.purge)
COOKIE = 'lumen_session'
app.include_router(inspection_router(IDENTITY, records_for, COOKIE))
app.include_router(workbench_router(IDENTITY, records_for, COOKIE, vault_origin=CONFIG['vault_addr'], vault_tls=SERVICES.vault_tls))
LOCKS: dict[str, asyncio.Lock] = {}

app.include_router(contract_download_router(IDENTITY, SERVICES.contracts, COOKIE, LOCKS))
STYLE = (Path(__file__).parents[1] / 'static/style.css').read_text()
# Inline SVG gives the browser a new icon URL when the brand asset changes.
FAVICON = (Path(__file__).parents[1] / 'static/favicon.svg').read_text()


@app.middleware('http')
async def private_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == '/' or request.url.path.startswith(('/auth/', '/traces/', '/solicitud', '/laboratorio-rar', '/mi-espacio')):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'lumen', 'model': {key: CONFIG['model'].get(key) for key in
             ('provider', 'model', 'credential_source')},
            'models': [{key: profile.get(key) for key in ('provider', 'model', 'credential_source')}
                       for profile in model_profiles(CONFIG).values()],
            'task_agents_available': task_agents_ready(CONFIG)}


@app.get('/language/{language}')
def change_language(language: str, request: Request):
    if language not in {'en', 'es'}:
        return HTMLResponse('Unknown language', status_code=400)
    session = IDENTITY.sessions.get(request.cookies.get(COOKIE, ''))
    if session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked():
        return HTMLResponse(Translator(request_language(request))(
            'Espera a que termine la operación para cambiar de idioma.'), status_code=409)
    response = RedirectResponse(safe_return_path(request.query_params.get('next', '/')), status_code=303)
    response.set_cookie(LANGUAGE_COOKIE, language, max_age=31536000, httponly=True,
                        samesite='lax', secure=request.url.scheme == 'https')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/auth/login')
def login(request: Request):
    old = request.cookies.get(COOKIE)
    if old and LOCKS.setdefault(old, asyncio.Lock()).locked():
        return HTMLResponse(Translator(request_language(request))(
            'Espera a que termine la operación para cambiar de agente.'), status_code=409)
    try:
        # Validate before invalidating the existing session. A query parameter
        # can choose a new login, but cannot change an authenticated actor.
        session, url = IDENTITY.start(request.query_params.get('agent', 'legacy'))
    except AccessDenied as exc:
        return HTMLResponse(Translator(request_language(request))(str(exc)), status_code=400)
    if old:
        IDENTITY.sessions.pop(old, None)
        LOCKS.pop(old, None)
    session.language = request_language(request)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(COOKIE, session.sid, httponly=True, samesite='lax', max_age=600)
    response.headers['Cache-Control'] = 'no-store'
    return response


def login_error_html(t, title, detail=''):
    from html import escape
    return (f'<html lang="{t.language}"><head><title>Lumen</title></head><body>'
            '<nav style="text-align:right"><a href="/language/en">EN</a> / <a href="/language/es">ES</a></nav>'
            f'<h2>{escape(t(title))}</h2><p>{escape(t(detail))}</p>'
            f'<a href="/auth/login">{escape(t("Volver a entrar"))}</a></body></html>')


@app.get('/auth/callback')
async def callback(request: Request):
    t = Translator(request_language(request))
    try:
        if request.query_params.get('error'):
            raise AccessDenied('Se ha cancelado el inicio de sesión.')
        session = await IDENTITY.finish(request.cookies.get(COOKIE, ''),
                                        request.query_params.get('state', ''),
                                        request.query_params.get('code', ''))
    except (AccessDenied, KeyError, ValueError) as exc:
        logging.warning('OIDC callback rejected: %s', str(exc) if isinstance(exc, AccessDenied) else type(exc).__name__)
        return HTMLResponse(login_error_html(t, 'No se ha completado el inicio de sesión', 'La respuesta de Verify no es válida o ha caducado.'), status_code=400,
                            headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
    except Exception as exc:
        logging.warning('OIDC validation failed: %s', type(exc).__name__)
        return HTMLResponse(login_error_html(t, 'No se ha podido validar la identidad'), status_code=503,
                            headers={'Cache-Control': 'no-store'})
    session.language = t.language
    if os.environ.get('CHATBOT_VERIFY_ACCESS') == '1':
        from .verification import verify_session
        try:
            await verify_session(SERVICES, session)
        except Exception as exc:
            logging.warning('Live OBO check failed: %s', str(exc) if isinstance(exc, AccessDenied) else type(exc).__name__)
    response = RedirectResponse('/', status_code=303)
    response.set_cookie(COOKIE, session.sid, httponly=True, samesite='lax',
                        max_age=max(1, int(session.expires_at - time.time())))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@ui.page('/')
def home(request: Request):
    ui.colors(primary='#708558')
    ui.add_css(STYLE)
    ui.add_head_html('<meta name="color-scheme" content="light dark"><meta name="referrer" content="no-referrer">')
    session = IDENTITY.sessions.get(request.cookies.get(COOKIE, ''))
    if session and (not session.subject or session.expires_at <= time.time()):
        session = None
    t = page_language(request, session)
    role = role_for_groups(session.groups, CONFIG['runtime']['groups']) if session else None
    role_label = ('Supervisor · datos sensibles' if session and SERVICES.can_reveal(session) else
                  {'readonly': 'Solo lectura', 'readwrite': 'Gestor · crear solicitudes'}.get(role, 'Sin acceso a datos'))
    dark = ui.dark_mode()
    # Theme is a browser preference only, never an identity or authorization input.
    dark.bind_value(app.storage.browser, 'dark')
    busy = False
    message_rows = session.display_messages if session else []
    profiles = model_profiles(CONFIG)
    preferred = app.storage.user.get('model_provider')
    selected = preferred if preferred in profiles else CONFIG['model'].get('provider')
    if session:
        if session.model_provider not in profiles:
            session.model_provider = selected or ''
        selected = session.model_provider

    def choose_provider(provider):
        nonlocal selected
        if busy or (session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked()):
            ui.notify(t('Espera a que termine la respuesta para cambiar de proveedor.'))
            return
        if provider not in profiles:
            ui.notify(t('Este proveedor todavía no está configurado.'), type='warning')
            return
        try:
            if session:
                ensure_session()
                select_provider(CONFIG, session, provider)
            selected = provider
            app.storage.user['model_provider'] = provider
            provider_banner.refresh()
        except AccessDenied as exc:
            ui.notify(t(str(exc)), type='warning')

    @ui.refreshable
    def provider_banner():
        active = session.model_provider if session else selected
        profile = profiles.get(active, {})
        with ui.element('section').classes('model-banner').props(t.props('aria-label="Proveedor de inteligencia artificial"')):
            ui.icon('auto_awesome', size='19px').classes('model-banner-icon')
            with ui.element('div').classes('model-banner-copy'):
                with ui.column().classes('gap-1'):
                    ui.label(t('Elige tu asistente')).classes('model-banner-name')
                    ui.label(t(profile.get('model', 'Sin configurar'))).classes('model-banner-method').props('aria-live="polite"')
                with ui.element('div').classes('provider-options').props(t.props('role="group" aria-label="Seleccionar proveedor"')):
                    for provider, label in PROVIDER_LABELS.items():
                        button = ui.button(t(label), color=None, on_click=lambda p=provider: choose_provider(p))
                        button.classes('provider-option' + (' provider-active' if provider == active else ''))
                        button.props(t.props('unelevated no-caps aria-pressed="' + str(provider == active).lower() + '"'))
                        if provider not in profiles or busy:
                            button.disable()
                        if provider not in profiles:
                            button.tooltip(t('Pendiente de configurar'))
                        else:
                            button.tooltip(t(profiles[provider]['model']))
                ui.label(t('Puedes cambiar para la siguiente consulta.')).classes('model-banner-method')


    def ensure_session():
        if not session or IDENTITY.sessions.get(session.sid) is not session:
            raise AccessDenied('Entra con Verify para comenzar.')
        session.require_login()

    def logout():
        if session:
            IDENTITY.sessions.pop(session.sid, None)
            LOCKS.pop(session.sid, None)
            session.messages.clear()
            session.display_messages.clear()
            session.access_token = ''
            session.pending = None
        ui.navigate.to('/auth/login')

    def clear_chat():
        if busy:
            ui.notify(t('Espera a que termine la respuesta para limpiar la conversación.'))
            return
        if session:
            session.messages.clear()
            session.pending = None
            session.catalogue_evidence = None
            session.events.clear()
        message_rows.clear()
        messages.refresh()
        activity.refresh()
        pending_view.refresh()

    @ui.refreshable
    def messages():
        with ui.column().classes('messages'):
            for who, text in message_rows:
                with ui.element('div').classes('message message-' + who):
                    ui.label(t('Tú' if who == 'user' else 'Lumen')).classes('message-label')
                    if who == 'user':
                        ui.label(text).style('white-space:pre-wrap')
                    else:
                        ui.markdown(text, sanitize=True)

    @ui.refreshable
    def activity():
        with ui.element('div').classes('info-card activity-card'):
            ui.label(t('Actividad de esta conversación')).classes('info-title')
            if not session or not session.events:
                ui.label(t('Aquí verás cómo se autoriza cada consulta.')).classes('tiny muted')
            else:
                for event in session.events[-5:]:
                    with ui.element('div').classes('activity'):
                        ui.label(event['time'] + ' · ' + t(event['title'])).classes('activity-title')
                        ui.label(t(event['detail'])).classes('activity-detail')
            if session and session.traces:
                ui.link(t('Ver última traza'), '/traces/' + session.traces[-1], new_tab=True).classes('tiny')
                ui.label(t('Trace ID · ' + session.traces[-1])).classes('tiny muted').style('overflow-wrap:anywhere')

    async def confirm():
        async def action():
            result = await SERVICES.confirm_request(session)
            return t('Borrador **#{id}** guardado en MySQL. Es una solicitud ficticia; no se ha contratado ningún suministro.', id=result['id'])
        await perform(t('Confirmar borrador'), action)

    @ui.refreshable
    def pending_view():
        if session and session.pending:
            with ui.element('div').classes('pending'):
                ui.label(t('Revisa antes de guardar')).classes('info-title')
                ui.label(t(f'Plan {session.pending["plan_id"]} · {session.pending["note"]}')).classes('tiny')
                with ui.row().classes('mt-3 gap-2'):
                    ui.button(t('Continuar solicitud'), on_click=lambda: ui.navigate.to('/solicitud')).classes('primary')
                    ui.button(t('Cancelar'), on_click=lambda: cancel_pending()).props('flat').classes('icon-button')

    def cancel_pending():
        if session:
            session.pending = None
        pending_view.refresh()

    async def perform(label, action):
        nonlocal busy
        if busy:
            return
        busy = True
        provider_banner.refresh()
        sending.set_visibility(True)
        send_button.disable()
        message_rows.append(('user', label))
        messages.refresh()
        try:
            ensure_session()
            lock = LOCKS.setdefault(session.sid, asyncio.Lock())
            async with lock:
                with span('lumen.action', **{'user.id': session.subject, 'user.role': role or 'none'}) as current:
                    tid = trace_id()
                    session.traces.append(tid)
                    session.traces[:] = session.traces[-50:]
                    result = await action()
            ensure_session()
            message_rows.append(('assistant', result))
            session.messages.extend([{'role': 'user', 'content': label}, {'role': 'assistant', 'content': result}])
            session.messages[:] = session.messages[-20:]
        except AccessDenied as exc:
            message_rows.append(('assistant', t(str(exc))))
        except Exception:
            message_rows.append(('assistant', t('No he podido completar la consulta. Puedes reintentarlo; no se han mostrado credenciales ni detalles internos.')))
        finally:
            busy = False
            provider_banner.refresh()
            sending.set_visibility(False)
            send_button.enable()
            messages.refresh()
            pending_view.refresh()
            activity.refresh()

    async def send():
        text = composer.value.strip()
        if not text:
            return
        composer.value = ''
        await perform(text, lambda: reply(SERVICES, session, text, language=t.language))

    async def quick_plans():
        async def action():
            rows = await SERVICES.plans(session)
            return '**' + t('Catálogo de demostración') + '**\n\n' + table(rows, t.language) + '\n\n' + t('Precios ficticios para probar el acceso a datos.')
        await perform(t('Comparar los planes del catálogo'), action)

    async def quick_requests():
        async def action():
            rows = await SERVICES.requests(session)
            if not rows:
                return t('Todavía no tienes borradores guardados.')
            return '\n'.join(f'- **#{r["id"]}** · plan {r["plan_id"]} · {r["status"]}: {r["note"]}' for r in rows)
        await perform(t('Ver mis solicitudes'), action)

    async def quick_search():
        async def action():
            rows = await SERVICES.search(session, 'autoconsumo')
            return '**' + t('Fuentes sobre autoconsumo compartido') + '**\n\n' + '\n\n'.join(
                f'[{r["title"]}]({r["url"]})\n\n{r["content"][:450]}' for r in rows)
        await perform(t('Buscar información pública sobre autoconsumo'), action)

    async def draft_dialog():
        if session and not task_allows(session, 'write'):
            ui.notify(t('Este agente no puede crear solicitudes. Selecciona Creación de solicitudes.'), type='warning')
            return
        try:
            ensure_session()
            if SERVICES.role(session) != 'readwrite':
                raise AccessDenied('Tu grupo solo permite consultar datos.')
        except AccessDenied as exc:
            async def denied():
                SERVICES.event(session, 'Escritura bloqueada', 'El grupo solo permite lectura. No se envía ninguna petición a Vault.', status='denied')
                raise AccessDenied('Tu grupo solo permite consultar datos. Esta acción se bloquea en la aplicación antes de llamar a Vault.')
            await perform(t('Intentar preparar una solicitud'), denied)
            return
        ui.navigate.to('/solicitud')

    mount_live_call_flow(session, language=t.language,
                        is_busy=lambda: busy or bool(session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked()),
                        is_current=lambda: bool(session and IDENTITY.sessions.get(session.sid) is session))
    agent_controls = task_agent_selector(CONFIG, session, t, lambda: busy or bool(
        session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked()))
    with ui.element('div').classes('shell'):
        with ui.element('aside').classes('rail'):
            ui.html(t('<div class="brand"><span class="brand-mark"></span>lumen<span style="font-size:14px;align-self:flex-start">®</span></div>'))
            ui.label(t('Un poco más de claridad')).classes('eyebrow')
            with ui.column().classes('rail-nav'):
                ui.button(t('Conversación'), icon='chat_bubble_outline').props('flat').classes('nav-button nav-active')
                ui.button(t('Planes de energía'), icon='light_mode', on_click=quick_plans).props('flat').classes('nav-button')
                ui.button(t('Solicitudes'), icon='description', on_click=lambda: ui.navigate.to('/solicitudes')).props('flat').classes('nav-button')
                ui.button(t('Laboratorio RAR'), icon='tune', on_click=lambda: ui.navigate.to('/laboratorio-rar')).props('flat').classes('nav-button')
                ui.button(t('Mi espacio de secretos'), icon='lock_outline', on_click=lambda: ui.navigate.to('/mi-espacio')).props('flat').classes('nav-button')
                ui.button(t('Borradores anteriores'), icon='history', on_click=quick_requests).props('flat').classes('nav-button')
                ui.button(t('Explorar en la web'), icon='public', on_click=quick_search).props('flat').classes('nav-button')
            ui.button(t('Nueva conversación'), icon='add', on_click=clear_chat).props('outline').classes('secondary w-full')
        with ui.element('main').classes('workspace'):
            with ui.element('header').classes('topbar'):
                ui.html(t('<div class="desktop-label eyebrow"><span class="status-dot"></span>Asistente de energía</div><div class="mobile-brand brand"><span class="brand-mark"></span>lumen</div>'))
                with ui.element('div').classes('top-actions'):
                    ui.label(t('Laboratorio')).classes('pill')
                    if session:
                        ui.label(session.name).classes('pill identity-pill')
                    ui.button(icon='contrast', on_click=dark.toggle).props(t.props('flat round aria-label="Cambiar tema"')).classes('icon-button').tooltip(t('Modo claro / oscuro'))
                    ui.button(icon='add_comment', on_click=clear_chat).props(t.props('flat round aria-label="Limpiar conversación"')).classes('icon-button').tooltip(t('Nueva conversación'))
                    if session:
                        ui.button(icon='logout', on_click=logout).props(t.props('flat round aria-label="Cambiar usuario"')).classes('icon-button').tooltip(t('Cambiar usuario'))
                    else:
                        ui.button(t('Entrar con Verify'), icon='arrow_outward', on_click=lambda: ui.navigate.to('/auth/login')).classes('primary')
                    lab_http_badge(request, t.language)
                    language_switch(request, t, lambda: busy or bool(session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked()))
            provider_banner()
            agent_controls()
            with ui.element('div').classes('content-grid'):
                with ui.element('section').classes('conversation'):
                    with ui.element('div').classes('welcome'):
                        ui.html(t('<div class="orb"></div>'))
                        ui.html(t('<h1>Tu energía,<br>con <em>claridad.</em></h1>'))
                        ui.label(t('Compara planes, resuelve tus dudas y encuentra tu siguiente paso. Yo te acompaño.')).classes('muted').style('max-width:490px;line-height:1.7;font-size:15px')
                    with ui.element('div').classes('suggestions'):
                        for icon, title, caption, handler in [
                            ('light_mode', 'Encuentra tu plan', 'Consulta el catálogo de energía', quick_plans),
                            ('public', 'Una mirada más amplia', 'Explora información en la web', quick_search),
                            ('edit_note', 'Da el siguiente paso', 'Completa tu solicitud en cinco pasos', draft_dialog),
                        ]:
                            with ui.button(on_click=handler).props('flat').classes('suggestion'):
                                ui.icon(icon, size='22px')
                                with ui.element('div'):
                                    ui.label(t(title)).classes('suggestion-title')
                                    ui.label(t(caption)).classes('suggestion-caption')
                    if not session:
                        ui.label(t('Entra con Verify para consultar el catálogo y conversar. Tu grupo determina si puedes consultar o también guardar solicitudes.')).classes('notice')
                    elif not role:
                        ui.label(t('Tu cuenta está autenticada, pero no pertenece a un grupo con acceso a los datos.')).classes('notice')
                    messages()
                    pending_view()
                    sending = ui.label(t('Lumen está preparando tu respuesta…')).classes('loading-line')
                    sending.set_visibility(False)
                    with ui.element('div').classes('composer'):
                        composer = ui.textarea(placeholder=t('¿Qué te gustaría saber sobre tu energía?')).props(t.props('autogrow borderless rows=2 maxlength=4000 aria-label="Tu mensaje"')).classes('w-full')
                        composer.on('keydown.enter.exact.prevent', send)
                        with ui.element('div').classes('composer-footer'):
                            ui.label(t('Enter para enviar · Mayús + Enter para nueva línea')).classes('composer-hint')
                            send_button = ui.button(icon='arrow_upward', on_click=send).props(t.props('flat aria-label="Enviar mensaje"')).classes('send')
                    ui.label(t('Demostración con datos ficticios. Ninguna acción contrata un suministro.')).classes('fineprint')
                with ui.element('aside').classes('inspector'):
                    with ui.element('div').classes('info-card'):
                        ui.label(t('TU ESPACIO')).classes('eyebrow mb-4')
                        ui.label(session.name if session else t('Todo empieza contigo')).classes('identity-name')
                        ui.label(t('Identidad verificada por IBM Verify' if session else 'Una sesión, acceso a tu medida.')).classes('tiny muted mt-2')
                        ui.label(t(role_label if session else 'Pendiente de iniciar sesión')).classes('access-badge')
                    activity()
                    if session:
                        ui.button(t('Comprobar límites en Vault'), icon='policy', on_click=lambda: perform(
                            t('Comprobar mis permisos en Vault'), lambda: SERVICES.permission_probe(session, language=t.language))).props('flat').classes('tiny')


async def application_page(request, renderer):
    ui.colors(primary='#708558')
    ui.add_css(STYLE)
    dark = ui.dark_mode()
    dark.bind_value(app.storage.browser, 'dark')
    session = IDENTITY.sessions.get(request.cookies.get(COOKIE, ''))
    t = page_language(request, session)
    mount_live_call_flow(session, language=t.language,
                        is_busy=lambda: bool(session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked()),
                        is_current=lambda: bool(session and IDENTITY.sessions.get(session.sid) is session))
    def guard():
        if not session or IDENTITY.sessions.get(session.sid) is not session:
            raise AccessDenied('Entra con Verify para continuar.')
        session.require_login()
    async def run_action(name, action):
        guard()
        async with LOCKS.setdefault(session.sid, asyncio.Lock()):
            guard()
            with span(name, **{'user.id': session.subject, 'user.role': SERVICES.role(session),
                               'agent.identity': 'chatbot-' + actor_credential(CONFIG, session.task_agent),
                               'agent.mode': session.task_agent,
                               'user.can_reveal': SERVICES.can_reveal(session)}):
                session.traces.append(trace_id())
                session.traces[:] = session.traces[-50:]
                return await action()
    def sign_in_panel(message):
        with ui.element('section').classes('application-sign-in'):
            ui.label(t('TU ESPACIO LUMEN')).classes('eyebrow')
            ui.label(t(message)).classes('sign-in-title').props('role=heading aria-level=1')
            ui.label(t('Accede a tus solicitudes con tu cuenta de Verify.')).classes('sign-in-description')
            ui.link(t('Entrar con Verify'), '/auth/login').classes('primary sign-in-action')

    agent_controls = task_agent_selector(CONFIG, session, t, lambda: bool(
        session and LOCKS.setdefault(session.sid, asyncio.Lock()).locked()))
    with ui.element('main').classes('application-shell') as shell:
        if renderer in (render_rar_lab, render_personal_spaces):
            shell.classes('rar-lab')
        try:
            guard()
        except AccessDenied as exc:
            shell.classes('application-login-shell')
            with ui.element('header').classes('sign-in-header'):
                with ui.link(target='/').classes('brand application-brand').props(t.props('aria-label="Lumen, inicio"')):
                    ui.element('span').classes('brand-mark').props('aria-hidden=true')
                    ui.label(t('lumen'))
                lab_http_badge(request, t.language)
                language_switch(request, t)
                ui.button(icon='contrast', on_click=dark.toggle).props(t.props('flat round aria-label="Cambiar tema"')).classes('icon-button')
            sign_in_panel(str(exc))
            return
        with ui.row().classes('application-tools'):
            lab_http_badge(request, t.language)
            language_switch(request, t, lambda: LOCKS.setdefault(session.sid, asyncio.Lock()).locked())
            ui.button(icon='contrast', on_click=dark.toggle).props(t.props('flat round aria-label="Cambiar tema"')).classes('icon-button')
        agent_controls()
        # Deliver the shell before initial catalogue/list calls so their spans
        # can be observed while the asynchronous renderer is still working.
        await ui.context.client.connected()
        try:
            await renderer(SERVICES, session, guard, run_action, language=t.language)
        except AccessDenied as exc:
            sign_in_panel(str(exc))


@ui.page('/solicitud')
async def application_new(request: Request):
    await application_page(request, render_wizard)


@ui.page('/solicitudes')
async def application_list(request: Request):
    await application_page(request, render_applications)


@ui.page('/laboratorio-rar')
async def rar_laboratory(request: Request):
    await application_page(request, render_rar_lab)


@ui.page('/mi-espacio')
async def personal_workspace(request: Request):
    await application_page(request, render_personal_spaces)


@ui.page('/traces/{tid}')
async def trace_page(tid: str, request: Request):
    t = page_language(request)
    ui.add_css(STYLE)
    with ui.row().classes('trace-language-bar'):
        language_switch(request, t)
    session = IDENTITY.sessions.get(request.cookies.get(COOKIE, ''))
    if not session or session.expires_at <= time.time() or tid not in session.traces:
        ui.label(t('Traza no disponible para esta sesión.'))
        return
    ui.colors(primary='#708558')
    ui.add_css(STYLE)
    records = sorted(records_for({tid}), key=lambda r: r['start_ns'])
    ui.label(t('Lumen · Traza de ejecución')).classes('text-3xl m-6')
    with ui.row().classes('w-full items-center justify-between px-6 gap-4 mb-4'):
        ui.label(t(tid)).classes('font-mono break-all')
        with ui.link(target=grafana_trace_url(tid, records), new_tab=True).classes(
                'primary inline-flex items-center gap-2 px-5 py-3 no-underline').props('rel="noopener noreferrer"'):
            ui.label(t('Ver en Grafana'))
            ui.icon('open_in_new', size='18px')
    from .trace_flow import build_flow
    flow = build_flow(records)
    agent_details = await SERVICES.agent_inspector.describe_many({c['agent_name'] for c in flow['calls'] if c.get('agent_name')})
    TraceFlow(records, tid, language=t.language, agent_details=agent_details, selected_span=request.query_params.get('span', ''))
    start = min((r['start_ns'] for r in records), default=0)
    rows = [dict(name=r['name'], start=round((r['start_ns']-start)/1e6), duration=r['duration_ms'],
                 status=r['status'], detail=json.dumps({k: v for k, v in r['attributes'].items() if k not in CONTENT_KEYS}, ensure_ascii=False)) for r in records]
    with ui.expansion(t('Tabla técnica · todos los spans'), icon='table_rows').classes('w-full px-6'):
        ui.table(columns=[{'name': key, 'label': t(label), 'field': key, 'align': 'left'} for key, label in
                          [('name', 'Paso'), ('start', 'Inicio (ms)'), ('duration', 'Duración (ms)'),
                           ('status', 'Estado'), ('detail', 'Metadatos')]], rows=rows, pagination=20).classes('w-full').props('wrap-cells')
        ui.label(t('UNSET significa que no se fijó un estado explícito. Las denegaciones registradas muestran ERROR / HTTP 403.'))
    ui.label(t('Contenido del modelo y herramientas · los intercambios sensibles se abren en el paso correspondiente del diagrama.')).classes('mx-6 my-4 text-grey')
    labels = {'lumen.user.message': 'Pregunta del usuario', 'gen_ai.input.messages': 'Entrada completa al modelo',
              'gen_ai.output.messages': 'Respuesta y llamadas a herramientas', 'gen_ai.tool.definitions': 'Herramientas disponibles',
              'lumen.model.parameters': 'Parámetros de la llamada', 'gen_ai.tool.call.arguments': 'Argumentos de la herramienta',
              'gen_ai.tool.call.result': 'Resultado de la herramienta',
              'vault.http.request': 'Petición enviada a Vault · cabeceras y cuerpo',
              'vault.auth.jwt': 'JWT completo presentado a Vault',
              'vault.auth.jwt.decoded': 'JWT decodificado · cabecera y claims',
              'spiffe.jwt_svid': 'JWT-SVID completo emitido por Vault',
              'spiffe.jwt_svid.decoded': 'JWT-SVID · cabecera, claims y validación de firma',
              'openai.exchange.subject_token': 'JWT-SVID enviado a OpenAI como subject_token',
              'anthropic.exchange.assertion': 'JWT-SVID de un solo uso enviado a Claude como assertion',
              'vault.http.response': 'Respuesta de Vault · incluye credenciales en modo laboratorio'}
    labels = {key: title for key, title in labels.items()
              if key not in VAULT_CONTENT_KEYS | SPIFFE_CONTENT_KEYS}
    for record in records:
        attrs = record['attributes']
        if not labels.keys() & attrs.keys():
            continue
        label = record['name'] + (t(' · llamada {number}', number=attrs['lumen.model.call_index']) if 'lumen.model.call_index' in attrs else '')
        if attrs.get('vault.path'):
            label += ' · ' + attrs['vault.path']
        with ui.expansion(t(label), icon='data_object').classes('w-full px-6'):
            for key, title in labels.items():
                if key in attrs:
                    ui.label(t(title)).classes('text-lg mt-4')
                    if attrs.get(key + '.truncated'):
                        ui.label(t('Contenido truncado por el límite de tamaño.')).classes('text-amber')
                    ui.code(json.dumps(json.loads(attrs[key]), indent=2, ensure_ascii=False), language='json').classes('w-full')
    ui.link(t('Volver al chat'), '/').classes('m-6')


ui.run(host='127.0.0.1', port=8088, title='Lumen · Tu energía, con claridad', favicon=FAVICON,
       reload=False, show=False, language='es', storage_secret=CONFIG['runtime']['session_secret'],
       show_welcome_message=False, uvicorn_logging_level='warning')
