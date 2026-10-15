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

from .agent import reply
from .security import AccessDenied, Identity, load_config, role_for_groups
from .services import Services
from .telemetry import records_for, span, trace_id
from .trace_content import CONTENT_KEYS
from .trace_links import grafana_trace_url
from .application_ui import render_wizard, render_applications

CONFIG = load_config()
IDENTITY = Identity(CONFIG)
SERVICES = Services(CONFIG, IDENTITY)
COOKIE = 'lumen_session'
LOCKS: dict[str, asyncio.Lock] = {}
STYLE = (Path(__file__).parents[1] / 'static/style.css').read_text()
# Inline SVG gives the browser a new icon URL when the brand asset changes.
FAVICON = (Path(__file__).parents[1] / 'static/favicon.svg').read_text()


@app.middleware('http')
async def private_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == '/' or request.url.path.startswith(('/auth/', '/traces/', '/solicitud')):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'lumen', 'model': {key: CONFIG['model'].get(key) for key in
             ('provider', 'model', 'credential_source')}}


@app.get('/auth/login')
def login(request: Request):
    old = request.cookies.get(COOKIE)
    if old:
        IDENTITY.sessions.pop(old, None)
    session, url = IDENTITY.start()
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(COOKIE, session.sid, httponly=True, samesite='lax', max_age=600)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/auth/callback')
async def callback(request: Request):
    try:
        if request.query_params.get('error'):
            raise AccessDenied('Se ha cancelado el inicio de sesión.')
        session = await IDENTITY.finish(request.cookies.get(COOKIE, ''),
                                        request.query_params.get('state', ''),
                                        request.query_params.get('code', ''))
    except (AccessDenied, KeyError, ValueError) as exc:
        logging.warning('OIDC callback rejected: %s', str(exc) if isinstance(exc, AccessDenied) else type(exc).__name__)
        return HTMLResponse('<h2>No se ha completado el inicio de sesión</h2><p>La respuesta de Verify no es válida o ha caducado.</p><a href="/auth/login">Volver a entrar</a>', status_code=400,
                            headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
    except Exception as exc:
        logging.warning('OIDC validation failed: %s', type(exc).__name__)
        return HTMLResponse('<h2>No se ha podido validar la identidad</h2><a href="/auth/login">Reintentar</a>', status_code=503,
                            headers={'Cache-Control': 'no-store'})
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
    role = role_for_groups(session.groups, CONFIG['runtime']['groups']) if session else None
    role_label = ('Supervisor · datos sensibles' if session and SERVICES.can_reveal(session) else
                  {'readonly': 'Solo lectura', 'readwrite': 'Gestor · crear solicitudes'}.get(role, 'Sin acceso a datos'))
    dark = ui.dark_mode()
    # Theme is a browser preference only, never an identity or authorization input.
    dark.bind_value(app.storage.browser, 'dark')
    busy = False
    message_rows = session.display_messages if session else []

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
            ui.notify('Espera a que termine la respuesta para limpiar la conversación.')
            return
        if session:
            session.messages.clear()
            session.pending = None
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
                    ui.label('Tú' if who == 'user' else 'Lumen').classes('message-label')
                    if who == 'user':
                        ui.label(text).style('white-space:pre-wrap')
                    else:
                        ui.markdown(text, sanitize=True)

    @ui.refreshable
    def activity():
        with ui.element('div').classes('info-card activity-card'):
            ui.label('Actividad de esta conversación').classes('info-title')
            if not session or not session.events:
                ui.label('Aquí verás cómo se autoriza cada consulta.').classes('tiny muted')
            else:
                for event in session.events[-5:]:
                    with ui.element('div').classes('activity'):
                        ui.label(event['time'] + ' · ' + event['title']).classes('activity-title')
                        ui.label(event['detail']).classes('activity-detail')
            if session and session.traces:
                ui.link('Ver última traza', '/traces/' + session.traces[-1], new_tab=True).classes('tiny')
                ui.label('Trace ID · ' + session.traces[-1]).classes('tiny muted').style('overflow-wrap:anywhere')

    async def confirm():
        async def action():
            result = await SERVICES.confirm_request(session)
            return f'Borrador **#{result["id"]}** guardado en MySQL. Es una solicitud ficticia; no se ha contratado ningún suministro.'
        await perform('Confirmar borrador', action)

    @ui.refreshable
    def pending_view():
        if session and session.pending:
            with ui.element('div').classes('pending'):
                ui.label('Revisa antes de guardar').classes('info-title')
                ui.label(f'Plan {session.pending["plan_id"]} · {session.pending["note"]}').classes('tiny')
                with ui.row().classes('mt-3 gap-2'):
                    ui.button('Continuar solicitud', on_click=lambda: ui.navigate.to('/solicitud')).classes('primary')
                    ui.button('Cancelar', on_click=lambda: cancel_pending()).props('flat').classes('icon-button')

    def cancel_pending():
        if session:
            session.pending = None
        pending_view.refresh()

    async def perform(label, action):
        nonlocal busy
        if busy:
            return
        busy = True
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
            message_rows.append(('assistant', str(exc)))
        except Exception:
            message_rows.append(('assistant', 'No he podido completar la consulta. Puedes reintentarlo; no se han mostrado credenciales ni detalles internos.'))
        finally:
            busy = False
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
        await perform(text, lambda: reply(SERVICES, session, text))

    async def quick_plans():
        async def action():
            rows = await SERVICES.plans(session)
            return '**Catálogo de demostración**\n\n| Plan | €/kWh | Descripción |\n|---|---:|---|\n' + '\n'.join(
                f'| {r["name"]} | {r["price_kwh"]:.4f} | {r["description"]} |' for r in rows) + '\n\nPrecios ficticios para probar el acceso a datos.'
        await perform('Comparar los planes del catálogo', action)

    async def quick_requests():
        async def action():
            rows = await SERVICES.requests(session)
            if not rows:
                return 'Todavía no tienes borradores guardados.'
            return '\n'.join(f'- **#{r["id"]}** · plan {r["plan_id"]} · {r["status"]}: {r["note"]}' for r in rows)
        await perform('Ver mis solicitudes', action)

    async def quick_search():
        async def action():
            rows = await SERVICES.search(session, 'autoconsumo')
            return '**Fuentes sobre autoconsumo compartido**\n\n' + '\n\n'.join(
                f'[{r["title"]}]({r["url"]})\n\n{r["content"][:450]}' for r in rows)
        await perform('Buscar información pública sobre autoconsumo', action)

    async def draft_dialog():
        try:
            ensure_session()
            if SERVICES.role(session) != 'readwrite':
                raise AccessDenied('Tu grupo solo permite consultar datos.')
        except AccessDenied as exc:
            async def denied():
                SERVICES.event(session, 'Escritura bloqueada', 'El grupo solo permite lectura. No se envía ninguna petición a Vault.', status='denied')
                raise AccessDenied('Tu grupo solo permite consultar datos. Esta acción se bloquea en la aplicación antes de llamar a Vault.')
            await perform('Intentar preparar una solicitud', denied)
            return
        ui.navigate.to('/solicitud')

    with ui.element('div').classes('shell'):
        with ui.element('aside').classes('rail'):
            ui.html('<div class="brand"><span class="brand-mark"></span>lumen<span style="font-size:14px;align-self:flex-start">®</span></div>')
            ui.label('Un poco más de claridad').classes('eyebrow')
            with ui.column().classes('rail-nav'):
                ui.button('Conversación', icon='chat_bubble_outline').props('flat').classes('nav-button nav-active')
                ui.button('Planes de energía', icon='light_mode', on_click=quick_plans).props('flat').classes('nav-button')
                ui.button('Solicitudes', icon='description', on_click=lambda: ui.navigate.to('/solicitudes')).props('flat').classes('nav-button')
                ui.button('Borradores anteriores', icon='history', on_click=quick_requests).props('flat').classes('nav-button')
                ui.button('Explorar en la web', icon='public', on_click=quick_search).props('flat').classes('nav-button')
            ui.button('Nueva conversación', icon='add', on_click=clear_chat).props('outline').classes('secondary w-full')
            with ui.element('div').classes('rail-bottom'):
                ui.label('Tu identidad, tus permisos.').style('font-weight:600;color:var(--ink)')
                ui.label('Cada consulta accede únicamente a lo que tienes autorizado.')
                ui.label('IBM Verify × HashiCorp Vault').classes('eyebrow mt-4').style('font-size:8px;letter-spacing:1px')
        with ui.element('main').classes('workspace'):
            with ui.element('header').classes('topbar'):
                ui.html('<div class="desktop-label eyebrow"><span class="status-dot"></span>Asistente de energía</div><div class="mobile-brand brand"><span class="brand-mark"></span>lumen</div>')
                with ui.element('div').classes('top-actions'):
                    ui.label('Laboratorio').classes('pill')
                    if session:
                        ui.label(session.name).classes('pill identity-pill')
                    ui.button(icon='contrast', on_click=dark.toggle).props('flat round aria-label="Cambiar tema"').classes('icon-button').tooltip('Modo claro / oscuro')
                    ui.button(icon='add_comment', on_click=clear_chat).props('flat round aria-label="Limpiar conversación"').classes('icon-button').tooltip('Nueva conversación')
                    if session:
                        ui.button(icon='logout', on_click=logout).props('flat round aria-label="Cambiar usuario"').classes('icon-button').tooltip('Cambiar usuario')
                    else:
                        ui.button('Entrar con Verify', icon='arrow_outward', on_click=lambda: ui.navigate.to('/auth/login')).classes('primary')
            with ui.element('div').classes('model-banner').props('role="status" aria-label="Modelo e integración"'):
                ui.icon('auto_awesome', size='19px').classes('model-banner-icon')
                with ui.element('div').classes('model-banner-copy'):
                    provider_label = {'xai': 'xAI', 'openai': 'OpenAI'}.get(CONFIG['model'].get('provider'), 'Modelo pendiente')
                    ui.label(provider_label + ' · ' + CONFIG['model'].get('model', 'Sin configurar')).classes('model-banner-name')
                    integration = {'vault_dynamic': 'Secret Engine · clave dinámica de Vault',
                                   'vault_spiffe': 'SPIFFE JWT-SVID · Vault → OpenAI'}.get(CONFIG['model'].get('credential_source'), 'Integración pendiente')
                    ui.label(integration).classes('model-banner-method')
            with ui.element('div').classes('content-grid'):
                with ui.element('section').classes('conversation'):
                    with ui.element('div').classes('welcome'):
                        ui.html('<div class="orb"></div>')
                        ui.html('<h1>Tu energía,<br>con <em>claridad.</em></h1>')
                        ui.label('Compara planes, resuelve tus dudas y encuentra tu siguiente paso. Yo te acompaño.').classes('muted').style('max-width:490px;line-height:1.7;font-size:15px')
                    with ui.element('div').classes('suggestions'):
                        for icon, title, caption, handler in [
                            ('light_mode', 'Encuentra tu plan', 'Consulta el catálogo de energía', quick_plans),
                            ('public', 'Una mirada más amplia', 'Explora información en la web', quick_search),
                            ('edit_note', 'Da el siguiente paso', 'Completa tu solicitud en cinco pasos', draft_dialog),
                        ]:
                            with ui.button(on_click=handler).props('flat').classes('suggestion'):
                                ui.icon(icon, size='22px')
                                with ui.element('div'):
                                    ui.label(title).classes('suggestion-title')
                                    ui.label(caption).classes('suggestion-caption')
                    if not session:
                        ui.label('Entra con Verify para consultar el catálogo y conversar. Tu grupo determina si puedes consultar o también guardar solicitudes.').classes('notice')
                    elif not role:
                        ui.label('Tu cuenta está autenticada, pero no pertenece a un grupo con acceso a los datos.').classes('notice')
                    messages()
                    pending_view()
                    sending = ui.label('Lumen está preparando tu respuesta…').classes('loading-line')
                    sending.set_visibility(False)
                    with ui.element('div').classes('composer'):
                        composer = ui.textarea(placeholder='¿Qué te gustaría saber sobre tu energía?').props('autogrow borderless rows=2 maxlength=4000 aria-label="Tu mensaje"').classes('w-full')
                        composer.on('keydown.enter.exact.prevent', send)
                        with ui.element('div').classes('composer-footer'):
                            ui.label('Enter para enviar · Mayús + Enter para nueva línea').classes('composer-hint')
                            send_button = ui.button(icon='arrow_upward', on_click=send).props('flat aria-label="Enviar mensaje"').classes('send')
                    ui.label('Demostración con datos ficticios. Ninguna acción contrata un suministro.').classes('fineprint')
                with ui.element('aside').classes('inspector'):
                    with ui.element('div').classes('info-card'):
                        ui.label('TU ESPACIO').classes('eyebrow mb-4')
                        ui.label(session.name if session else 'Todo empieza contigo').classes('identity-name')
                        ui.label('Identidad verificada por IBM Verify' if session else 'Una sesión, acceso a tu medida.').classes('tiny muted mt-2')
                        ui.label(role_label if session else 'Pendiente de iniciar sesión').classes('access-badge')
                    with ui.element('div').classes('info-card'):
                        ui.label('Cómo protegemos tus datos').classes('info-title')
                        for n, title, caption in [('1', 'Tu identidad', 'Verify confirma quién eres y tu grupo.'),
                                                  ('2', 'Tu autorización', 'Vault limita cada operación del agente.'),
                                                  ('3', 'Solo lo necesario', 'MySQL recibe una credencial temporal.')]:
                            with ui.element('div').classes('flow-step'):
                                ui.label(n).classes('flow-number')
                                with ui.element('div'):
                                    ui.label(title).classes('tiny').style('font-weight:550')
                                    ui.label(caption).classes('tiny muted')
                    activity()
                    if session:
                        ui.button('Comprobar límites en Vault', icon='policy', on_click=lambda: perform(
                            'Comprobar mis permisos en Vault', lambda: SERVICES.permission_probe(session))).props('flat').classes('tiny')


async def application_page(request, renderer):
    ui.colors(primary='#708558')
    ui.add_css(STYLE)
    dark = ui.dark_mode()
    dark.bind_value(app.storage.browser, 'dark')
    session = IDENTITY.sessions.get(request.cookies.get(COOKIE, ''))
    def guard():
        if not session or IDENTITY.sessions.get(session.sid) is not session:
            raise AccessDenied('Entra con Verify para continuar.')
        session.require_login()
    async def run_action(name, action):
        guard()
        async with LOCKS.setdefault(session.sid, asyncio.Lock()):
            guard()
            with span(name, **{'user.id': session.subject, 'user.role': SERVICES.role(session),
                               'user.can_reveal': SERVICES.can_reveal(session)}):
                session.traces.append(trace_id())
                session.traces[:] = session.traces[-50:]
                return await action()
    def sign_in_panel(message):
        with ui.element('section').classes('application-sign-in'):
            ui.label('TU ESPACIO LUMEN').classes('eyebrow')
            ui.label(message).classes('sign-in-title').props('role=heading aria-level=1')
            ui.label('Accede a tus solicitudes con tu cuenta de Verify.').classes('sign-in-description')
            ui.link('Entrar con Verify', '/auth/login').classes('primary sign-in-action')

    with ui.element('main').classes('application-shell') as shell:
        try:
            guard()
        except AccessDenied as exc:
            shell.classes('application-login-shell')
            with ui.element('header').classes('sign-in-header'):
                with ui.link(target='/').classes('brand application-brand').props('aria-label="Lumen, inicio"'):
                    ui.element('span').classes('brand-mark').props('aria-hidden=true')
                    ui.label('lumen')
                ui.button(icon='contrast', on_click=dark.toggle).props('flat round aria-label="Cambiar tema"').classes('icon-button')
            sign_in_panel(str(exc))
            return
        ui.button(icon='contrast', on_click=dark.toggle).props('flat round aria-label="Cambiar tema"').classes('flow-theme')
        try:
            await renderer(SERVICES, session, guard, run_action)
        except AccessDenied as exc:
            sign_in_panel(str(exc))


@ui.page('/solicitud')
async def application_new(request: Request):
    await application_page(request, render_wizard)


@ui.page('/solicitudes')
async def application_list(request: Request):
    await application_page(request, render_applications)


@ui.page('/traces/{tid}')
def trace_page(tid: str, request: Request):
    session = IDENTITY.sessions.get(request.cookies.get(COOKIE, ''))
    if not session or session.expires_at <= time.time() or tid not in session.traces:
        ui.label('Traza no disponible para esta sesión.')
        return
    ui.colors(primary='#708558')
    ui.add_css(STYLE)
    records = sorted(records_for({tid}), key=lambda r: r['start_ns'])
    ui.label('Lumen · Traza de ejecución').classes('text-3xl m-6')
    with ui.row().classes('w-full items-center justify-between px-6 gap-4 mb-4'):
        ui.label(tid).classes('font-mono break-all')
        with ui.link(target=grafana_trace_url(tid, records), new_tab=True).classes(
                'primary inline-flex items-center gap-2 px-5 py-3 no-underline').props('rel="noopener noreferrer"'):
            ui.label('Ver en Grafana')
            ui.icon('open_in_new', size='18px')
    ui.label('Mensajes del modelo, control de ámbito y herramientas. En modo laboratorio se incluyen los intercambios con Vault y el JWT-SVID emitido y enviado a OpenAI, sin ocultar valores.').classes('mx-6 text-grey')
    start = min((r['start_ns'] for r in records), default=0)
    rows = [dict(name=r['name'], start=round((r['start_ns']-start)/1e6), duration=r['duration_ms'],
                 status=r['status'], detail=json.dumps({k: v for k, v in r['attributes'].items() if k not in CONTENT_KEYS}, ensure_ascii=False)) for r in records]
    ui.table(columns=[{'name': key, 'label': label, 'field': key, 'align': 'left'} for key, label in
                      [('name', 'Paso'), ('start', 'Inicio (ms)'), ('duration', 'Duración (ms)'),
                       ('status', 'Estado'), ('detail', 'Metadatos')]], rows=rows, pagination=20).classes('w-full p-6').props('wrap-cells')
    ui.label('Los errores esperados en las pruebas de límites muestran ERROR / HTTP 403.').classes('mx-6')
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
              'vault.http.response': 'Respuesta de Vault · incluye credenciales en modo laboratorio'}
    for record in records:
        attrs = record['attributes']
        if not CONTENT_KEYS.intersection(attrs):
            continue
        label = record['name'] + (f' · llamada {attrs["lumen.model.call_index"]}' if 'lumen.model.call_index' in attrs else '')
        if attrs.get('vault.path'):
            label += ' · ' + attrs['vault.path']
        with ui.expansion(label, icon='data_object').classes('w-full px-6'):
            for key, title in labels.items():
                if key in attrs:
                    ui.label(title).classes('text-lg mt-4')
                    if attrs.get(key + '.truncated'):
                        ui.label('Contenido truncado por el límite de tamaño.').classes('text-amber')
                    ui.code(json.dumps(json.loads(attrs[key]), indent=2, ensure_ascii=False), language='json').classes('w-full')
    ui.link('Volver al chat', '/').classes('m-6')


ui.run(host='127.0.0.1', port=8088, title='Lumen · Tu energía, con claridad', favicon=FAVICON,
       reload=False, show=False, language='es', storage_secret=CONFIG['runtime']['session_secret'],
       show_welcome_message=False, uvicorn_logging_level='warning')
