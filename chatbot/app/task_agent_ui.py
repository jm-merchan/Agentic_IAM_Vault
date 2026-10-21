"""Task selection is an explicit login action, never an in-place actor change."""
from nicegui import ui

from .task_agents import TASK_AGENTS, task_agents_ready, task_label
from .permission_matrix import AGENTS, PROFILES, current_profile, decisions, summary


def permission_matrix(config, session, t, on_select=None):
    """Return a preview callback; exploration never changes the login or actor."""
    current = current_profile(config, session)
    active = session.task_agent if current else None
    profiles = dict(PROFILES)
    if current and current[0] not in profiles:
        profiles[current[0]] = current[1:]
    selected = [current[0] if current else 'reader', active or 'legacy']

    def choose(profile, mode):
        selected[:] = [profile, mode]
        if on_select:
            on_select(mode)
        render.refresh()

    @ui.refreshable
    def render():
        with ui.element('section').classes('permission-matrix').props(t.props('aria-label="Matriz de permisos OBO"')):
            with ui.element('div').classes('permission-heading'):
                with ui.column().classes('gap-1'):
                    ui.label(t('Permisos esperados · OBO')).classes('eyebrow')
                    if current:
                        ui.label(t('Tu sesión: {user} + {agent}', user=t(current[1]), agent=t(AGENTS.get(active, 'Sin acceso a datos')))).classes('permission-title')
                        ui.label(session.name or session.subject).classes('muted tiny')
                    else:
                        ui.label(t('Compara usuarios y agentes')).classes('permission-title')
                if current:
                    ui.label(summary(current[2], active, t)).classes('permission-current-summary')
            ui.label(t('El usuario y el agente deben permitir la operación. Vault decide en cada llamada.')).classes('muted')
            with ui.element('div').classes('permission-table-scroll').props(t.props('tabindex="0" role="region" aria-label="Comparación de permisos por usuario y agente"')):
                with ui.element('table').classes('permission-table'):
                    with ui.element('caption').classes('sr-only'):
                        ui.label(t('Permisos esperados según el usuario y el agente elegido'))
                    with ui.element('thead'):
                        with ui.element('tr'):
                            with ui.element('th').props('scope="col"'):
                                ui.label(t('Usuario autenticado'))
                            for mode, label in AGENTS.items():
                                with ui.element('th').props('scope="col"').classes('permission-active-column' if mode == active else ''):
                                    ui.label(t(label))
                                    if mode == active:
                                        ui.label(t('Agente activo')).classes('permission-marker')
                    with ui.element('tbody'):
                        for key, (label, operations) in profiles.items():
                            with ui.element('tr').classes('permission-current-row' if current and key == current[0] else ''):
                                with ui.element('th').props('scope="row"'):
                                    ui.label(t(label))
                                    if current and key == current[0]:
                                        ui.label(t('Tu perfil')).classes('permission-marker')
                                for mode, agent_label in AGENTS.items():
                                    is_current = bool(current and key == current[0] and mode == active)
                                    is_selected = selected == [key, mode]
                                    classes = 'permission-cell'
                                    if is_current:
                                        classes += ' permission-cell-current'
                                    if is_selected:
                                        classes += ' permission-cell-selected'
                                    with ui.element('td').classes(classes):
                                        with ui.button(on_click=lambda k=key, m=mode: choose(k, m)).props('flat no-caps').classes('permission-choice') as cell:
                                            cell.props['aria-label'] = t('Comparar {user} con {agent}', user=t(label), agent=t(agent_label))
                                            cell.props['aria-pressed'] = str(is_selected).lower()
                                            if is_current:
                                                cell.props['aria-current'] = 'true'
                                            ui.label(summary(operations, mode, t))
                                            if is_current:
                                                ui.label(t('Tu sesión')).classes('permission-marker')
            ui.label(t('Pulsa una celda para comparar. Su agente se selecciona también en el desplegable; tu sesión no cambia hasta que lo actives.')).classes('muted tiny')
            key, mode = selected
            label, operations = profiles[key]
            is_current = bool(current and key == current[0] and mode == active)
            with ui.element('div').classes('permission-explanation').props('aria-live="polite" aria-atomic="true"'):
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label(t('Tu combinación') if is_current else t('Vista previa: {user} + {agent}', user=t(label), agent=t(AGENTS[mode]))).classes('text-weight-medium')
                    if current and not is_current:
                        ui.button(t('Volver a mi combinación'), on_click=lambda: choose(current[0], active)).props('flat dense no-caps')
                with ui.element('div').classes('permission-decisions'):
                    for decision in decisions(operations, mode):
                        with ui.element('div').classes('permission-decision'):
                            ui.label(t(decision['label'])).classes('text-weight-medium')
                            ui.label(t('Usuario: {value} · Agente: {agent}',
                                       value=t('Sí' if decision['user'] else 'No'),
                                       agent=t('Sí' if decision['agent'] else 'No'))).classes('tiny')
                            if decision['expected']:
                                reason = 'Ambos lo permiten'
                            elif not decision['user'] and not decision['agent']:
                                reason = 'Lo limitan el usuario y el agente'
                            elif not decision['user']:
                                reason = 'Lo limita el usuario'
                            else:
                                reason = 'Lo limita el agente'
                            with ui.row().classes('gap-1 items-center'):
                                ui.icon('check_circle' if decision['expected'] else 'block', size='16px')
                                ui.label(t(reason)).classes('tiny')
            ui.label(t('Verify autentica y emite el token OBO. Vault aplica: usuario ∩ techo del agente ∩ RAR de la petición.')).classes('permission-formula')
            ui.label(t('Esta matriz orienta según los perfiles de la demo; no consulta las políticas actuales de Vault. El RAR y otros bloqueos pueden restringir más. «Comprobar límites en Vault» prueba las llamadas reales.')).classes('muted tiny')
    render()

    def preview(mode):
        # set_value also emits the select's change event. Keep the clicked row
        # when that event merely acknowledges a table selection.
        if selected[1] != mode:
            choose(current[0] if current else selected[0], mode)

    return preview


def task_agent_selector(config, session, t, blocked=lambda: False):
    """Create a top-level responsive drawer and return its compact launcher."""
    ready = task_agents_ready(config)
    active = session.task_agent if session else 'legacy'
    profile = current_profile(config, session)
    title = t('Agentes por tarea') + ' · ' + t(task_label(session))
    if profile:
        title += ' · ' + t(profile[1]) + ' → ' + summary(profile[2], active, t)
    launcher = None
    with ui.right_drawer(value=False, bordered=True).props('width=760 breakpoint=1700').classes('task-permission-drawer') as drawer:
        drawer.props['aria-label'] = t('Agentes y permisos')
        with ui.element('div').classes('task-drawer-heading'):
            with ui.column().classes('gap-1'):
                ui.label(t('Agentes por tarea')).classes('permission-title')
                ui.label(t('Compara permisos y elige el agente de tu próxima sesión.')).classes('muted tiny')
            close_button = ui.button(icon='close', on_click=drawer.hide).props(t.props('flat round aria-label="Cerrar panel de permisos"')).classes('icon-button')
        body = ui.element('div').classes('task-agent-body')

    def update_open_state(e):
        if launcher:
            launcher.props['aria-expanded'] = str(bool(e.value)).lower()

    drawer.on_value_change(update_open_state)
    # Focus after the drawer transition, when its controls are visible.
    drawer.on('show', js_handler=f'() => getHtmlElement({close_button.id})?.focus({{preventScroll: true}})')
    drawer.on('keydown.escape', drawer.hide)
    with body:
        selector = None

        def sync_selection(mode):
            if selector is not None and selector.value != mode:
                selector.set_value(mode)

        preview = permission_matrix(config, session, t, on_select=sync_selection)
        if ready:
            choices = {'legacy': t('Modo actual')}
            choices.update({key: t(task['label']) for key, task in TASK_AGENTS.items()})
            selector = ui.select(choices, value=active, label=t('Identidad del agente'),
                                 on_change=lambda e: preview(e.value)).classes('w-full').props('outlined')
            ui.label(t('Cambiar de agente abre Verify y comienza una sesión nueva. Guarda el borrador antes de cambiar.')).classes('muted')

            def activate():
                if blocked():
                    ui.notify(t('Espera a que termine la operación para cambiar de agente.'), type='warning')
                    return
                if session and selector.value == active:
                    return
                ui.navigate.to('/auth/login?agent=' + selector.value)

            ui.button(t('Activar y entrar con Verify'), on_click=activate, icon='login').props('no-caps').classes('self-start')
        else:
            ui.label(t('Esta ampliación todavía no está instalada. El modo actual sigue disponible.')).classes('muted')
        ui.link(t('Abrir laboratorio de parámetros RAR'), '/laboratorio-rar').classes('task-rar-link')
        ui.link(t('Mi espacio de secretos'), '/mi-espacio').classes('task-rar-link')

    def render_launcher():
        nonlocal launcher
        with ui.button(on_click=drawer.toggle).props('flat no-caps').classes('task-agent-launcher') as launcher:
            launcher.props['aria-label'] = t('Abrir panel de permisos')
            launcher.props['aria-expanded'] = str(bool(drawer.value)).lower()
            launcher.props['aria-controls'] = f'c{drawer.id}'
            ui.icon('account_tree', size='22px')
            ui.label(title).classes('task-launcher-label')
            ui.icon('view_sidebar', size='21px')
        drawer.on('hide', js_handler=f'() => getHtmlElement({launcher.id})?.focus({{preventScroll: true}})')
        return launcher

    return render_launcher
