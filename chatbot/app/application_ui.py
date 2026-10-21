"""A guided energy application and a shared lab queue, with explicit reveal actions."""
from __future__ import annotations

from uuid import uuid4

from nicegui import ui

from .applications import DEMO_FORM, STEPS, document_hint, generate_demo_form, iban_hint, validate_form
from .task_agents import task_allows
from .security import AccessDenied
from .i18n import Translator


def page_header(session, role_name, title, subtitle, language=None):
    t = Translator(language or session.language)
    with ui.element('header').classes('application-header'):
        with ui.link(target='/').classes('brand application-brand').props(t.props('aria-label="Lumen, inicio"')):
            ui.element('span').classes('brand-mark').props('aria-hidden=true')
            ui.label(t('lumen'))
        with ui.row().classes('items-center gap-3'):
            ui.label(t(role_name)).classes('pill')
            ui.label(session.name).classes('tiny muted')
            ui.link(t('Volver al chat'), '/').classes('tiny')
    ui.label(t(title)).classes('application-title')
    ui.label(t(subtitle)).classes('application-subtitle')


async def render_wizard(services, session, guard, run_action, language=None):
    t = Translator(language or session.language)
    guard()
    if services.role(session) != 'readwrite' or not task_allows(session, 'write'):
        page_header(session, 'Solo consulta', 'Tu acceso es de consulta.', 'Puedes revisar las solicitudes y los permisos disponibles para tu perfil.', language=t.language)
        ui.link(t('Ver solicitudes'), '/solicitudes').classes('primary')
        return
    if session.application_draft is None:
        pending = session.pending or {}
        session.application_draft = {'id': str(uuid4()), 'form': {
            **{key: '' for key in DEMO_FORM}, 'plan_id': pending.get('plan_id', 1), 'note': pending.get('note', ''),
        }}
    draft = session.application_draft
    form = draft['form']
    if 'suggestions' not in draft:
        draft['suggestions'] = generate_demo_form()
    suggestions = draft['suggestions']
    step = draft.get("step", 0)
    busy = False
    confirmed = False
    error = ''
    saved = ''
    plans = await run_action('lumen.application.catalog', lambda: services.plans(session))
    plan_map = {p['id']: p for p in plans}
    page_header(session, 'Gestor', 'Vamos a dar el siguiente paso.', 'Una solicitud, a tu ritmo. Completa los datos y revísalos antes de guardar.', language=t.language)

    def back_to(index):
        nonlocal step, error, confirmed
        guard()
        if busy or saved:
            return
        step, error, confirmed = index, '', False
        draft['step'] = step
        body.refresh()
        ui.run_javascript('window.scrollTo({top: 0, behavior: "smooth"})')

    def next_step():
        nonlocal step, error
        try:
            guard()
            form.update(validate_form(form, step=step))
            step += 1
            draft["step"] = step
            error = ''
        except AccessDenied as exc:
            error = str(exc)
        body.refresh()
        ui.run_javascript('window.scrollTo({top: 0, behavior: "smooth"})')

    def use_demo():
        nonlocal confirmed
        guard()
        if busy:
            return
        form.update(suggestions)
        confirmed = False
        body.refresh()
        ui.notify(t('Datos ficticios cargados. Puedes recorrer y revisar cada paso.'))

    def suggested_input(label, key):
        label = t(label)
        suggestion = suggestions[key]
        if key == 'iban':
            suggestion = ' '.join(suggestion[i:i + 4] for i in range(0, len(suggestion), 4))
        field = ui.input(t(label), placeholder=t(suggestion)).bind_value(form, key).props(
            t.props('outlined stack-label autocomplete=off'))

        def accept():
            nonlocal confirmed
            guard()
            if not busy and not saved and not str(field.value or '').strip():
                field.set_value(suggestion)
                confirmed = False

        # Let native Tab move focus; only forward an acceptance for an empty field.
        # Shift+Tab and manually entered values retain normal browser behavior.
        field.on('keydown.tab', accept, js_handler='''(event) => {
            if (!event.shiftKey && !event.target.value.trim()) emit();
        }''')
        if key in ('dni', 'iban'):
            with field.add_slot('append'):
                ui.button(icon='auto_fix_high', on_click=accept).props(
                    t.props(f'flat round dense tabindex=-1 aria-label="Usar dato de prueba para {label}"')
                ).classes('muted').tooltip(t('Aceptar sugerencia de prueba · Tab'))
        return field

    async def save():
        nonlocal busy, error, saved
        if busy or saved:
            return
        try:
            guard()
            if not confirmed:
                raise AccessDenied('Confirma que has revisado los datos de esta solicitud de demostración.')
            form.update(validate_form(form))
            busy, error = True, ''
            body.refresh()
            saved = await run_action('lumen.application.submit', lambda: services.save_application(session, dict(form), draft['id']))
            # Remove clear form data from session memory after persistence.
            session.application_draft = None
            session.pending = None
            form.clear()
        except AccessDenied as exc:
            error = str(exc)
        except Exception:
            error = 'No se ha podido guardar. Puedes reintentarlo con la misma referencia sin crear duplicados.'
        finally:
            busy = False
            body.refresh()
            ui.run_javascript('window.scrollTo({top: 0, behavior: "smooth"})')

    @ui.refreshable
    def body():
        nonlocal confirmed
        if saved:
            with ui.element('section').classes('application-success'):
                ui.icon('check_circle', size='58px').classes('success-icon')
                ui.label(t('Solicitud recibida.')).classes('text-3xl mt-4')
                ui.label(t('Todo listo para continuar la demostración. No se ha contratado ningún suministro.')).classes('muted mt-3')
                ui.label(t('Referencia · ' + saved)).classes('application-reference')
                ui.label(t('Tus datos se han guardado protegidos.')).classes('mt-4')
                ui.link(t('Ver solicitudes'), '/solicitudes').classes('primary mt-5')
                ui.link(t('Ver traza de esta solicitud'), '/traces/' + session.traces[-1], new_tab=True).classes('tiny mt-4')
            return
        with ui.element('div').classes('application-steps'):
            for index, title in enumerate(STEPS):
                with ui.button(on_click=lambda index=index: back_to(index)).props('flat').classes(
                    'application-step ' + ('current' if index == step else 'complete' if index < step else '')) as step_button:
                    ui.label(str(index + 1)).classes('step-number')
                    ui.label(t(title))
                if index >= step or busy:
                    step_button.disable()
        with ui.element('div').classes('application-grid'):
            with ui.element('section').classes('application-panel'):
                ui.label(t(f'PASO {step + 1} DE 5')).classes('eyebrow')
                titles = ['Elige cómo quieres tu energía.', '¿Dónde está tu vivienda?', 'Conozcamos al titular.', 'Tu cuenta, con tranquilidad.', 'Todo claro antes de guardar.']
                descriptions = ['Tres tarifas ficticias para esta demostración.', 'Indica la dirección del punto de suministro.',
                                'Estos datos se introducen en el formulario, fuera de la conversación.',
                                'El titular de la cuenta será el titular de la solicitud. No se realiza ningún cargo.',
                                'Comprueba la tarifa, la dirección y los datos del titular. Puedes volver a cualquier paso.']
                ui.label(t(titles[step])).classes('text-2xl mt-3')
                ui.label(t(descriptions[step])).classes('muted text-sm mb-6')
                if error:
                    ui.label(t(error)).classes('application-error').props('role=alert')
                if step in (1, 2, 3):
                    with ui.row().classes('items-center no-wrap gap-2 mb-5'):
                        ui.icon('keyboard_tab', size='20px').classes('muted')
                        ui.label(t('Datos ficticios sugeridos. Pulsa Tab en un campo vacío para aceptar y avanzar.')).classes('tiny muted')
                if step == 0:
                    for plan in plans:
                        def choose(pid=plan['id']):
                            form['plan_id'] = pid
                            body.refresh()
                        with ui.button(on_click=choose).props('flat no-caps').classes('tariff-option ' + ('selected' if form['plan_id'] == plan['id'] else '')):
                            with ui.row().classes('w-full justify-between items-center'):
                                ui.label(plan['name']).classes('text-lg')
                                ui.icon('radio_button_checked' if form['plan_id'] == plan['id'] else 'radio_button_unchecked')
                            ui.label(t(t.number(plan['price_kwh']) + ' €/kWh')).classes('tariff-price')
                            ui.label(t(plan['description'])).classes('text-left text-sm muted')
                elif step == 1:
                    with ui.element('div').classes('form-grid'):
                        suggested_input('Calle o vía', 'street').props('maxlength=140').classes('span-two')
                        suggested_input('Número', 'number').props('maxlength=12')
                        suggested_input('Piso y puerta (opcional)', 'floor').props('maxlength=30')
                        suggested_input('Código postal', 'postal_code').props('maxlength=5 inputmode=numeric')
                        suggested_input('Localidad', 'city').props('maxlength=80')
                        suggested_input('Provincia', 'province').props('maxlength=80').classes('span-two')
                elif step == 2:
                    with ui.element('div').classes('form-grid'):
                        suggested_input('Nombre y apellidos', 'full_name').props('maxlength=120').classes('span-two')
                        suggested_input('DNI o NIE', 'dni').props('maxlength=12')
                        suggested_input('Teléfono', 'phone').props('maxlength=18 inputmode=tel')
                        suggested_input('Correo electrónico', 'email').props('maxlength=160 type=email').classes('span-two')
                elif step == 3:
                    ui.label(form['full_name']).classes('text-lg mb-3')
                    suggested_input('IBAN español', 'iban').props('maxlength=34').classes('w-full')
                    ui.label(t('Usaremos los cuatro últimos dígitos para identificar la cuenta en las consultas.')).classes('tiny muted mt-3')
                    ui.textarea(t('Nota (opcional)')).bind_value(form, 'note').props('outlined maxlength=500').classes('w-full mt-5')
                else:
                    with ui.element('div').classes('review-grid'):
                        for label, value in [('Tarifa', plan_map[form['plan_id']]['name']),
                                             ('Vivienda', f'{form["street"]}, {form["number"]} · {form["floor"]}'),
                                             ('Localidad', f'{form["postal_code"]} · {form["city"]}, {form["province"]}'),
                                             ('Titular', form['full_name']), ('Documento', document_hint(form['dni'])),
                                             ('Contacto', form['email'] + ' · ' + form['phone']), ('Cuenta', iban_hint(form['iban']))]:
                            with ui.element('div').classes('review-item'):
                                ui.label(t(label)).classes('eyebrow')
                                ui.label(value).classes('mt-2')
                    def consent(event):
                        nonlocal confirmed
                        confirmed = event.value
                    ui.checkbox(t('He revisado los datos de esta solicitud de demostración.'), value=confirmed, on_change=consent).classes('mt-5')
                with ui.row().classes('application-actions'):
                    if step:
                        ui.button(t('Atrás'), on_click=lambda: back_to(step - 1)).props('flat no-caps').classes('secondary').set_enabled(not busy)
                    if step < 4:
                        ui.button(t('Continuar'), icon='arrow_forward', on_click=next_step).props('no-caps').classes('primary')
                    else:
                        ui.button(t('Guardando…' if busy else 'Guardar solicitud'), icon='lock', on_click=save).props('no-caps').classes('primary').set_enabled(not busy)
            with ui.element('aside').classes('application-summary'):
                ui.label(t('TU ELECCIÓN')).classes('eyebrow')
                plan = plan_map.get(form['plan_id'], plans[0])
                ui.label(plan['name']).classes('text-2xl mt-3')
                ui.label(t(t.number(plan['price_kwh']))).classes('summary-price')
                ui.label(t('€/kWh · precio ficticio')).classes('muted text-sm')
                ui.separator().classes('my-5')
                for icon, text in [('eco', 'Energía y decisiones con claridad'), ('lock', 'Datos protegidos al guardar'), ('check_circle', 'Revisión antes de confirmar')]:
                    with ui.row().classes('items-center no-wrap mb-4'):
                        ui.icon(icon).classes('muted')
                        ui.label(t(text)).classes('text-sm')
                ui.button(t('Usar datos de prueba'), icon='science', on_click=use_demo).props('flat no-caps').classes('secondary w-full').set_enabled(not busy)
                ui.label(t('Solo laboratorio. Esta solicitud no es un contrato ni una orden de cobro.')).classes('tiny muted mt-4')
        ui.label(t('Puedes volver atrás sin perder lo que has escrito durante esta sesión.')).classes('tiny muted mt-4')
    body()


async def render_applications(services, session, guard, run_action, language=None):
    t = Translator(language or session.language)
    guard()
    role = services.role(session)
    supervisor = services.can_reveal(session)
    role_name = 'Supervisor' if supervisor else 'Gestor' if role == 'readwrite' else 'Lector'
    page_header(session, role_name, 'Cada solicitud, en su sitio.', 'Bandeja compartida del laboratorio. Los datos personales se muestran enmascarados hasta que Vault autoriza revelarlos.', language=t.language)
    with ui.row().classes('items-center gap-3 mb-5'):
        if role == 'readwrite' and task_allows(session, 'write'):
            ui.link(t('Nueva solicitud'), '/solicitud').classes('primary')
        ui.button(t('Actualizar'), icon='refresh', on_click=lambda: ui.navigate.to('/solicitudes')).props('flat no-caps').classes('secondary')
        ui.label(t('Puede revelar datos' if supervisor else 'Lectura enmascarada')).classes('access-badge')
    rows = await run_action('lumen.applications.list', lambda: services.applications(session))
    if not rows:
        with ui.element('div').classes('application-panel'):
            ui.label(t('Todavía no hay solicitudes en esta bandeja.')).classes('text-xl')
            ui.label(t('Entra como gestor para completar la primera. Los borradores antiguos siguen disponibles desde el chat.')).classes('muted mt-3')
        return

    async def reveal(reference):
        from .services import VaultPermissionDenied
        try:
            guard()
            profile = await run_action('lumen.application.reveal', lambda: services.reveal_application(session, reference))
        except VaultPermissionDenied:
            with ui.dialog() as denied, ui.card().classes('application-dialog'):
                ui.icon('lock', size='38px')
                ui.label(t('Estos datos requieren otro permiso.')).classes('text-2xl')
                ui.label(t('Vault ha denegado la recuperación de los datos sensibles. Puedes seguir consultando la información enmascarada.')).classes('muted')
                ui.link(t('Ver la petición y la denegación'), '/traces/' + session.traces[-1], new_tab=True)
                ui.button(t('Entendido'), on_click=denied.close).classes('primary')
            denied.open()
            return
        except AccessDenied as exc:
            ui.notify(t(str(exc)), type='warning')
            return
        except Exception:
            ui.notify(t('No se ha podido consultar Vault. Vuelve a intentarlo.'), type='negative')
            return
        with ui.dialog() as detail, ui.card().classes('application-dialog'):
            ui.label(t('Datos de la solicitud')).classes('text-2xl')
            ui.label(t('Vault ha autorizado esta consulta con tu identidad.')).classes('muted')
            for label, value in [('Titular', profile['full_name']), ('DNI / NIE', profile['dni']), ('IBAN', profile['iban']),
                                 ('Dirección', f'{profile["street"]}, {profile["number"]} {profile["floor"]}, {profile["postal_code"]} {profile["city"]}'),
                                 ('Contacto', profile['email'] + ' · ' + profile['phone'])]:
                with ui.element('div').classes('review-item w-full'):
                    ui.label(t(label)).classes('eyebrow')
                    ui.label(value).classes('mt-1 break-all')
            ui.link(t('Ver la traza de autorización'), '/traces/' + session.traces[-1], new_tab=True)
            ui.button(t('Ocultar y cerrar'), on_click=detail.close).classes('primary')
        # Removing the dialog also removes its rendered clear values from the browser DOM.
        detail.on('hide', lambda: detail.delete())
        detail.open()

    with ui.element('div').classes('application-list'):
        for row in rows:
            with ui.element('article').classes('application-panel request-card'):
                with ui.row().classes('w-full justify-between items-center'):
                    ui.label(row['plan_name']).classes('text-xl')
                    ui.label(t(row['status'])).classes('access-badge')
                ui.label(t('Referencia · ' + row['application_id'])).classes('application-reference')
                ui.label(row['created_at']).classes('tiny muted')
                ui.separator().classes('my-4')
                for label, value in [('DNI / NIE', row['dni_hint']), ('IBAN', row['iban_hint'])]:
                    with ui.row().classes('w-full justify-between'):
                        ui.label(t(label)).classes('muted text-sm')
                        ui.label(value).classes('text-sm')
                ui.label(t('Titular, contacto y dirección protegidos')).classes('tiny muted mt-3')
                ui.button(t('Revelar datos'), icon='visibility', on_click=lambda reference=row['application_id']: reveal(reference)).props('no-caps flat').classes('secondary mt-4')
    ui.link(t('Ver última traza'), '/traces/' + session.traces[-1], new_tab=True).classes('tiny mt-5')
