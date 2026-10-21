"""Interactive, optional RAR laboratory with real requests and trace links."""
import json
from datetime import datetime, timezone

from nicegui import ui

from .i18n import Translator
from .permission_matrix import current_profile, decisions
from .rar import authorization_details
from .rar_lab import INTERPRETATIONS, run_comparison, scenarios
from .security import AccessDenied
from .task_agents import actor_credential


async def render_rar_lab(services, session, guard, run_action, language=None):
    t = Translator(language or session.language)
    guard()
    catalog = scenarios(services.config)
    selected = session.rar_scenario if session.rar_scenario in catalog else 'allowed'
    busy = False
    user = current_profile(services.config, session)
    agent = 'chatbot-' + actor_credential(services.config, session.task_agent)
    with ui.row().classes('items-center justify-between w-full'):
        ui.label(t('Laboratorio RAR')).classes('text-3xl')
        ui.link(t('Volver al chat'), '/')
    ui.label(t('Compara la misma petición sin restricciones de parámetros y con ellas. Vault decide en ambos casos; el chat conserva su comportamiento habitual.')).classes('muted')
    with ui.element('div').classes('rar-identities'):
        with ui.card().classes('rar-identity'):
            ui.label(t('Usuario autenticado')).classes('eyebrow')
            ui.label(t(user[1]) if user else t('Sin acceso a datos')).classes('text-weight-bold')
            ui.label(session.name or session.subject).classes('tiny muted')
        with ui.card().classes('rar-identity'):
            ui.label(t('Agente en Vault')).classes('eyebrow')
            ui.label(agent).classes('text-weight-bold break-all')
            ui.label(t('El techo del agente sigue aplicándose.')).classes('tiny muted')
    ui.label(t('Se cifran y tokenizan datos ficticios y se descifran dos perfiles de prueba. No se guardan solicitudes ni se modifican filas de MySQL.')).classes('rar-notice')

    def choose(e):
        nonlocal selected
        selected = e.value
        session.rar_scenario = selected
        body.refresh()

    scenario_selector = ui.select({key: t(item['title']) for key, item in catalog.items()}, value=selected,
                                  label=t('Escenario RAR'), on_change=choose).props('outlined').classes('w-full')
    if 'decrypt' not in catalog:
        ui.label(t('El escenario de revelado requiere preparar los perfiles ficticios del laboratorio.')).classes('muted')

    @ui.refreshable
    def body():
        item = catalog[selected]
        expected = next(d for d in decisions(user[2] if user else set(), session.task_agent) if d['operation'] == item['operation'])
        ui.label(t(item['description'])).classes('rar-description')
        ui.label('POST /v1/' + item['path']).classes('rar-endpoint')
        with ui.element('div').classes('rar-access-summary'):
            ui.label(t('Acceso base esperado según los perfiles de la demo')).classes('text-weight-bold')
            ui.label(t('Usuario: {value} · Agente: {agent}', value=t('Sí' if expected['user'] else 'No'), agent=t('Sí' if expected['agent'] else 'No')))
            ui.label(t('La petición de control comprueba este acceso en Vault. Si también recibe 403, no se atribuye la denegación a los parámetros RAR.')).classes('tiny muted')
        with ui.element('div').classes('rar-rules'):
            for field in ('allowed_parameters', 'denied_parameters', 'required_parameters'):
                with ui.element('section').classes('rar-rule'):
                    ui.label(field).classes('text-weight-bold')
                    ui.code(json.dumps(item['parameters'][field], ensure_ascii=False, indent=2), language='json').classes('w-full') if field in item['parameters'] else ui.label(t('Sin restricción adicional')).classes('muted')
        with ui.expansion(t('RAR completo solicitado a Verify'), icon='data_object').classes('w-full'):
            ui.code(json.dumps(authorization_details(item['path'], ['update'], item['parameters']), ensure_ascii=False, indent=2), language='json').classes('w-full')

        cases = {'all': t('Todos los casos del escenario')} | {c['id']: t(c['label']) for c in item['cases']}
        case_selector = ui.select(cases, value='all', label=t('Caso de prueba')).props('outlined').classes('w-full')
        with ui.element('div').classes('rar-case-list'):
            for case in item['cases']:
                with ui.expansion(t(case['label']), icon='check_circle' if case['expected'] else 'block').classes('rar-case'):
                    ui.label(t('Regla RAR: {result}', result=t('Permitido' if case['expected'] else 'Denegado'))).classes('text-weight-bold')
                    ui.label(t(case['reason'])).classes('muted')
                    ui.code(json.dumps(case['payload'], ensure_ascii=False, indent=2), language='json').classes('w-full')
        with ui.row().classes('items-center gap-3'):
            execute_button = ui.button(t('Comparar peticiones reales'), icon='play_arrow').props('no-caps').classes('primary')
            progress = ui.label('').classes('muted').props('aria-live=polite')

        @ui.refreshable
        def result_view():
            saved = session.rar_results.get(item['id'])
            if not saved:
                return
            ui.label(t('Resultados de Vault')).classes('text-2xl mt-4')
            ui.label(saved['checked_at']).classes('tiny muted')
            with ui.element('div').classes('rar-results').props(t.props('tabindex=0 role=region aria-label="Resultados de la comparación RAR"')):
                with ui.element('table').classes('rar-result-table'):
                    with ui.element('thead'), ui.element('tr'):
                        for heading in ('Caso', 'Regla RAR', 'Control sin parámetros', 'Con parámetros RAR', 'Interpretación', 'Traza'):
                            with ui.element('th').props('scope=col'):
                                ui.label(t(heading))
                    with ui.element('tbody'):
                        for row in saved['rows']:
                            with ui.element('tr'):
                                with ui.element('th').props('scope=row'):
                                    ui.label(t(row['label']))
                                with ui.element('td'):
                                    ui.label(t('Permitido' if row['expected'] else 'Denegado'))
                                for phase in ('baseline', 'restricted'):
                                    data = row['phases'][phase]
                                    with ui.element('td'):
                                        status = data['status']
                                        ui.label(f'HTTP {status}' if status else t('Sin respuesta de Vault')).classes('rar-code ' + ('rar-denied' if status == 403 else 'rar-ok' if status == 200 else ''))
                                        if data['error']:
                                            ui.label(t(data['error'])).classes('tiny')
                                with ui.element('td'):
                                    ui.label(t(INTERPRETATIONS[row['interpretation']]))
                                with ui.element('td'):
                                    for phase, caption in [('baseline', 'Ver control'), ('restricted', 'Ver restricción')]:
                                        target = '/traces/' + row['trace_id'] + '?span=' + row['phases'][phase]['span_id']
                                        ui.link(t(caption), target, new_tab=True).classes('block')
            ui.label(t('HTTP 403 es una denegación real de Vault. Un error de Verify, de conexión o del motor no se cuenta como una restricción RAR demostrada.')).classes('tiny muted')
        result_view()

        async def execute():
            nonlocal busy
            if busy:
                return
            busy = True
            execute_button.disable()
            scenario_selector.disable()
            case_selector.disable()
            saved = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'rows': []}
            session.rar_results[item['id']] = saved
            def receive(row):
                saved['rows'].append(row)
                progress.set_text(t('{count} comparaciones completadas', count=len(saved['rows'])))
                result_view.refresh()
            try:
                guard()
                progress.set_text(t('Ejecutando Verify y Vault…'))
                await run_action('lumen.rar.compare', lambda: run_comparison(services, session, item['id'], case_selector.value, receive))
            except AccessDenied as exc:
                ui.notify(t(str(exc)), type='warning')
            except Exception:
                ui.notify(t('No se pudo completar la comparación. Consulta la traza.'), type='negative')
            finally:
                busy = False
                execute_button.enable()
                scenario_selector.enable()
                case_selector.enable()
                result_view.refresh()
        execute_button.on_click(execute)
    body()
