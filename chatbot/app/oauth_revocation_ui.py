"""Step-by-step browser lab, using the same JWT pair until explicit cleanup."""
import json
import time
from functools import partial

from nicegui import ui

from .i18n import Translator
from .security import AccessDenied
from .telemetry import records_for
from .trace_flow_ui import TraceFlow


async def render_oauth_revocation(services, session, guard, run_action, language=None):
    t = Translator(language or session.language)
    guard()
    manager = services.oauth_revocation
    selected = 'delegated'
    busy = False
    expiry_timer = None
    with ui.row().classes('items-center justify-between w-full'):
        ui.label(t('Laboratorio de revocación OAuth')).classes('text-3xl')
        ui.link(t('Volver al chat'), '/')
    ui.label(t('Crea dos tokens y sus leases. Prueba las credenciales, revoca A y comprueba el JWT, el lease y el acceso al sistema final. B sirve de control.')).classes('muted')
    ui.label(t('El bloqueo se aplica en Vault. No revoca el token en Verify ni cambia las políticas del agente.')).classes('rar-notice')
    if not manager.available:
        ui.label(t('Reinicia Lumen con el script actualizado para preparar el laboratorio.')).classes('rar-notice')
        return

    def choose(e):
        nonlocal selected
        if expiry_timer:
            expiry_timer.cancel()
        selected = e.value
        body.refresh()

    selector = ui.select({'delegated': t('Delegado · usuario + agente (OBO)'),
                          'direct': t('Directo · agente (Client Credentials)')},
                         value=selected, label=t('Tipo de acceso'), on_change=choose).props('outlined').classes('w-full')

    @ui.refreshable
    def body():
        nonlocal expiry_timer
        if expiry_timer:
            expiry_timer.cancel()
        mode = selected
        saved = manager.view(session, mode)
        ui.label(t('Se usa tu usuario y el agente activo. Cada token genera una credencial MySQL de solo lectura; el acceso se prueba con una nueva conexión y SELECT 1.')
                 if mode == 'delegated' else t('Se usa chatbot-xai sin identidad humana. Cada token genera una API key dinámica; se prueba en GET /v1/api-key de xAI, sin inferencia.')).classes('rar-description')
        endpoint = 'database/creds/chatbot-readonly' if mode == 'delegated' else 'xai/creds/lumen'
        ui.label('GET /v1/' + endpoint).classes('rar-endpoint')
        buttons = []

        async def execute(action):
            nonlocal busy
            if busy:
                return
            busy = True
            selector.disable()
            for button in buttons:
                button.disable()
            try:
                guard()
                await run_action('lumen.oauth_revocation.' + action,
                                 lambda: getattr(manager, action)(session, mode))
            except AccessDenied as exc:
                ui.notify(t(str(exc)), type='warning')
            except Exception:
                ui.notify(t('No se pudo completar la prueba. Consulta la traza y vuelve a intentarlo.'), type='negative')
            finally:
                busy = False
                selector.enable()
                body.refresh()

        with ui.column().classes('w-full gap-3'):
            for text, action, enabled, icon in (
                ('1. Crear tokens y leases', 'prepare', True, 'add_circle_outline'),
                ('2. Probar acceso al sistema final', 'access', bool(saved and len(saved['tokens']) == 2 and not saved['blocked']), 'login'),
                ('3. Revocar token A', 'block', bool(saved and saved['accessed'] and not saved['blocked']), 'block'),
                ('4. Verificar token, lease y acceso', 'check', bool(saved and saved['blocked']), 'play_arrow'),
            ):
                button = ui.button(t(text), icon=icon, on_click=partial(execute, action)).props('no-caps').classes('primary')
                button.set_enabled(enabled)
                buttons.append(button)
        if not saved:
            return
        with ui.row().classes('w-full items-center justify-between'):
            remaining = ui.label('').classes('tiny muted').props('role=status aria-live=polite')
            def clock():
                seconds = max(0, int(min((c['exp'] for c in saved['tokens']), default=0) - time.time()))
                lease_seconds = max(0, int(min((c['expires_at'] for c in saved['leases']), default=0) - time.time()))
                remaining.set_text(t('JWT: {seconds} s restantes · vencimiento original del lease: {lease_seconds} s. Revoca con más de 30 s de JWT y 15 s de lease.', seconds=seconds, lease_seconds=lease_seconds))
            clock()
            expiry_timer = ui.timer(1, clock)
            clear = ui.button(t('Limpiar tokens del lab'), icon='delete_outline', on_click=lambda: execute('clear')).props('flat no-caps')
            buttons.append(clear)
        with ui.expansion(t('Leases y acceso al sistema final'), icon='key', value=True).classes('w-full'):
            states = {'active': 'Activo', 'missing': 'No existe', 'unknown': 'No concluyente',
                      'accepted': 'Aceptado', 'rejected': 'Rechazado', '': 'Pendiente'}
            for label, lease in zip(('A', 'B'), saved['leases']):
                ui.label('Token ' + label + ' · ' + lease['lease_id']).classes('tiny break-all')
                ui.label(t('TTL inicial: {ttl} s · Vault: {state} · acceso antes: {before} · acceso después: {after}',
                    ttl=lease['ttl'], state=t(states[lease['state']]),
                    before=t(states[lease['before']]), after=t(states[lease['after']]))).classes('tiny muted')
            ui.label(t('Se conserva la misma credencial para las pruebas antes y después. No se revoca el lease por separado. Las contraseñas y API keys permanecen en el servidor.')).classes('tiny muted')
        with ui.expansion(t('Identidad de los tokens y petición de bloqueo'), icon='data_object').classes('w-full'):
            for label, claims in zip(('A', 'B'), saved['tokens']):
                ui.label('Token ' + label).classes('text-weight-bold')
                ui.code(json.dumps(claims, ensure_ascii=False, indent=2), language='json').classes('w-full')
            if saved['tokens']:
                claims = saved['tokens'][0]
                ui.label('POST /v1/auth/token/revoke-oauth').classes('rar-endpoint')
                ui.code(json.dumps({'issuer': claims['iss'], 'unique_id': claims['jti'],
                                    'exp': max(0, int(claims['exp'] - time.time())) + 16}, indent=2), language='json').classes('w-full')
                ui.label(t('issuer viene de iss; unique_id viene de jti. exp es la duración restante más 15 s de tolerancia, no la fecha exp del JWT. El valor se recalcula al pulsar Bloquear.')).classes('tiny muted')
                ui.label(t('La llamada usa un operador de Vault separado, limitado al issuer de Verify. Los JWT y la credencial del operador permanecen en el servidor.')).classes('tiny muted')
        ui.label(t('Resultados de la prueba')).classes('text-2xl mt-4')
        phases = {'before': 'Generar lease', 'revoke': 'Bloqueo en Vault', 'after': 'Acceso tras el bloqueo', 'cleanup': 'Limpieza',
                  'lease_before': 'Lease antes', 'lease_after': 'Lease después',
                  'system_before': 'Sistema antes', 'system_after': 'Sistema después'}
        with ui.element('div').classes('rar-results'):
            with ui.element('table').classes('rar-result-table'):
                with ui.element('thead'), ui.element('tr'):
                    for heading in ('Paso', 'Token', 'Sistema', 'Resultado', 'Traza'):
                        with ui.element('th').props('scope=col'):
                            ui.label(t(heading))
                with ui.element('tbody'):
                    for row in saved['rows']:
                        with ui.element('tr'):
                            with ui.element('td'): ui.label(t(phases[row['phase']]))
                            with ui.element('td'): ui.label(row['token'])
                            with ui.element('td'): ui.label(row['target'])
                            with ui.element('td'): ui.label(str(row['status'])).classes('rar-code')
                            with ui.element('td'): ui.link(t('Ver traza'), '/traces/' + row['trace_id'], new_tab=True)
        if saved['verified']:
            ui.label(t('Demostrado: A recibe 403, su lease ya no existe y su credencial deja de autenticar antes del vencimiento original. B conserva acceso en Vault, lease activo y acceso al sistema final.')).classes('rar-notice')
        elif saved['blocked'] and any(r['phase'] == 'after' for r in saved['rows']):
            ui.label(t('Resultado no concluyente: se exige bloqueo del JWT, lease de A ausente y credencial rechazada antes de caducar, con B funcionando en los tres niveles. Un error de conexión o consulta no demuestra revocación.')).classes('rar-notice')
        if saved['traces']:
            tid = saved['traces'][-1]
            ui.label(t('Flujo de la última acción')).classes('text-2xl mt-4')
            TraceFlow(records_for({tid}), trace_id=tid, language=t.language, inspection=False)
    body()
