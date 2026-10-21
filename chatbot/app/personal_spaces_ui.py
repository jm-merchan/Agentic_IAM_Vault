"""Optional personal KV workspace, central policy explanation and real probes."""
import json

from nicegui import ui

from .agent_details import vault_ui_url
from .i18n import Translator
from .personal_spaces import access, configuration, owner_for, secret_path
from .security import AccessDenied
from .task_agents import actor_credential


async def render_personal_spaces(services, session, guard, run_action, language=None):
    t = Translator(language or session.language)
    guard()
    with ui.row().classes('items-center justify-between w-full'):
        ui.label(t('Mi espacio de secretos')).classes('text-3xl')
        ui.link(t('Volver al chat'), '/')
    try:
        config = configuration(services.config)
        owner = owner_for(services.config, session.subject)
    except AccessDenied as exc:
        ui.label(t(str(exc))).classes('rar-notice')
        return
    writable = session.task_agent in ('legacy', 'write')
    ceiling = 'lumen-personal-' + ('write' if writable else 'read')
    agent = 'chatbot-' + actor_credential(services.config, session.task_agent)
    base = services.agent_inspector.base
    link = lambda path: vault_ui_url(base, path)
    ui.label(t('Secretos de prueba aislados por identidad humana. Vault decide cada acceso mediante OBO; estos valores no se envían al modelo.')).classes('muted')
    with ui.element('div').classes('personal-identities'):
        with ui.card().classes('personal-card'):
            ui.label(t('Propietario del espacio')).classes('eyebrow')
            ui.label(owner['name']).classes('text-weight-bold')
            ui.label(owner['entity_id']).classes('personal-path')
            ui.link(t('Abrir entidad en Vault'), link('access/identity/entities/' + owner['entity_id'] + '/details'), new_tab=True)
        with ui.card().classes('personal-card'):
            ui.label(t('Agente en Vault')).classes('eyebrow')
            ui.label(agent).classes('text-weight-bold')
            ui.label(t('Puede leer y guardar en tu espacio' if writable else 'Puede leer tu espacio; la escritura queda fuera de su techo'))
            ui.link(t('Abrir Agent Registry'), link('agents/registry'), new_tab=True)
    ui.label(t('Reader, Writer y Supervisor tienen un espacio propio. El rol de las solicitudes compartidas no concede acceso a espacios ajenos.')).classes('rar-notice')
    with ui.expansion(t('Por qué Vault permite o deniega'), icon='policy').classes('w-full'):
        ui.label(t('Vault sustituye identity.entity.id por la entidad humana del token OBO. El agente aporta su techo y el RAR solicita la ruta concreta.'))
        ui.label(t('Política central del propietario')).classes('text-weight-bold')
        ui.link('lumen-personal-user', link('policy/acl/lumen-personal-user'), new_tab=True)
        ui.code(config['policies']['user'], language='hcl').classes('w-full')
        ui.label(t('Techo del agente para espacios personales')).classes('text-weight-bold')
        ui.link(ceiling, link('policy/acl/' + ceiling), new_tab=True)
        ui.code(config['policies']['write' if writable else 'read'], language='hcl').classes('w-full')
        ui.label(t('Configuración publicada por el instalador. Los resultados de abajo comprueban el acceso real; puedes abrir las políticas actuales en Vault.')).classes('tiny muted')

    busy = False
    draft = session.personal_draft
    loaded = (draft.get('loaded_name', ''), draft.get('version', 0))
    controls = []
    with ui.element('section').classes('personal-card'):
        ui.label(t('Leer o guardar un secreto propio')).classes('text-xl')
        name = ui.input(t('Nombre del secreto'), value=draft.get('name', 'demo')).props('outlined maxlength=64').classes('w-full')
        controls.append(name)
        path_label = ui.label(secret_path(services.config, session.subject)).classes('personal-path')
        def show_path():
            draft['name'] = name.value
            try:
                path_label.set_text(secret_path(services.config, session.subject, name.value))
            except AccessDenied:
                path_label.set_text(t('Nombre de secreto no válido.'))
        name.on_value_change(show_path)
        show_path()
        editor = ui.textarea(t('Contenido del secreto · JSON'), value=draft.get('value', '{"note": "Dato ficticio de demostración"}')).props('outlined rows=6 spellcheck=false').classes('w-full personal-json')
        editor.on_value_change(lambda e: draft.update(value=e.value))
        controls.append(editor)
        ui.label(t('Guardar crea una versión de KV v2. Para modificar un secreto existente, léelo primero; una versión concurrente no se sobrescribe.')).classes('tiny muted')
        status = ui.label('').classes('personal-status').props('role=status aria-live=polite')

        async def execute(action, target=None):
            nonlocal busy, loaded
            if busy:
                return
            busy = True
            for control in controls:
                control.disable()
            try:
                guard()
                value = json.loads(editor.value) if action == 'write' else None
                status.set_text(t('Ejecutando Verify y Vault…'))
                result = await run_action('lumen.personal.' + action, lambda: access(
                    services, session, action, name=name.value, value=value,
                    version=loaded[1] if loaded[0] == name.value else 0, target=target))
                session.personal_results.append({k: v for k, v in result.items() if k != 'data'})
                session.personal_results[:] = session.personal_results[-12:]
                status.set_text(f'{result["target"]} · HTTP {result["status"]} · ' + (t(result['error']) if result['error'] else t('Operación completada en Vault.')))
                if result['status'] == 200 and target is None:
                    if action == 'read':
                        editor.set_value(json.dumps(result['data']['data'], indent=2, ensure_ascii=False))
                        loaded = (name.value, result['data']['metadata']['version'])
                    elif action == 'write':
                        loaded = (name.value, result['data']['version'])
                    else:
                        names.set_text(', '.join(result['data']['keys']))
                elif action == 'read' and target is None:
                    loaded = ('', 0)
                draft.update(loaded_name=loaded[0], version=loaded[1])
                results.refresh()
            except (ValueError, TypeError):
                status.set_text(t('Introduce un objeto JSON válido.'))
            except AccessDenied as exc:
                status.set_text(t(str(exc)))
            except Exception:
                status.set_text(t('No se pudo completar la operación. Consulta la traza.'))
            finally:
                busy = False
                for control in controls:
                    control.enable()

        with ui.row().classes('gap-3 flex-wrap'):
            controls.append(ui.button(t('Leer secreto'), icon='visibility', on_click=lambda: execute('read')).props('no-caps'))
            controls.append(ui.button(t('Guardar versión'), icon='save', on_click=lambda: execute('write')).props('no-caps'))
            controls.append(ui.button(t('Listar mi espacio'), icon='list', on_click=lambda: execute('list')).props('flat no-caps'))
        if not writable:
            ui.label(t('Puedes intentar guardar para observar el HTTP 403 real del techo del agente.')).classes('tiny muted')
        names = ui.label('').classes('personal-path')
    with ui.element('section').classes('personal-card'):
        ui.label(t('Comprobar aislamiento entre usuarios')).classes('text-xl')
        ui.label(t('Se solicita a Verify un RAR que permite leer la ruta elegida. Vault debe rechazar el acceso a otro propietario mediante su política central.')).classes('muted')
        choices = {u['subject']: u['name'] for u in config['users'] if u['subject'] != session.subject}
        target = ui.select(choices, value=next(iter(choices), None), label=t('Espacio de otro usuario')).props('outlined').classes('w-full')
        controls.append(target)
        ui.label(t('La prueba usa el mismo nombre de secreto indicado arriba. Lee primero el tuyo como control.')).classes('tiny muted')
        controls.append(ui.button(t('Intentar leer el espacio ajeno'), icon='policy', on_click=lambda: execute('read', target.value)).props('no-caps'))

    @ui.refreshable
    def results():
        if not session.personal_results:
            return
        ui.label(t('Resultados de Vault')).classes('text-2xl')
        for result in reversed(session.personal_results):
            with ui.element('section').classes('personal-result'):
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label(f'HTTP {result["status"]} · {result["target"]} · ' + t({'read': 'Leer secreto', 'write': 'Guardar versión', 'list': 'Listar mi espacio'}[result['action']])).classes('text-weight-bold')
                    ui.link(t('Ver petición y resultado'), '/traces/' + result['trace_id'] + '?span=' + result['span_id'], new_tab=True)
                ui.label(result['path']).classes('personal-path')
                ui.label(t('Esperado: {value}', value=t('Permitido' if result['expected'] else 'Denegado'))).classes('tiny')
                if result['status'] == 403:
                    ui.label(t('Denegación real de Vault; el RAR sí solicitaba esta ruta.')).classes('muted')
                elif result['status'] == 200 and not result['expected']:
                    ui.label(t('Acceso inesperado: revisa las políticas actuales en Vault.')).classes('text-negative')
                elif result['status'] != 200:
                    ui.label(t('Este resultado no demuestra aislamiento. Revisa la petición y la respuesta.')).classes('muted')
                with ui.expansion('authorization_details').classes('w-full'):
                    ui.code(json.dumps(result['rar'], indent=2), language='json').classes('w-full')
    results()
