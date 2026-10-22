"""Small, session-scoped live projection; never an inspector or request console."""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path

from nicegui import ui
from nicegui.element import Element

from .i18n import Translator
from .telemetry import records_for
from .trace_flow import ACTORS, build_flow

STATIC = Path(__file__).parents[1] / 'static'
ICONS = {path.stem: f'data:image/{"svg+xml" if path.suffix == ".svg" else "png"};base64,'
         + base64.b64encode(path.read_bytes()).decode('ascii')
         for path in (STATIC / 'service-icons').iterdir() if path.suffix in {'.svg', '.png'}}
COPY = {
    'es': dict(title='Flujo de llamadas', eyebrow='ESTA EJECUCIÓN', expand='Abrir flujo de llamadas',
               collapse='Contraer flujo de llamadas', running='En curso', done='Finalizada',
               failed='Finalizada con errores', waiting='Esperando llamadas', empty='Las llamadas aparecerán al iniciar una operación.',
               login='Entrar con Verify', anonymous='Entra con Verify para ver el flujo de tu sesión.',
               hop='salto', hops='saltos', trace='Abrir traza', pending='En curso…', noResponse='Sin respuesta registrada',
               finished='Completada', local='Lab HTTP local', scroll='Diagrama de llamadas de esta ejecución'),
    'en': dict(title='Live call flow', eyebrow="THIS EXECUTION’S CALL FLOW", expand='Open call flow',
               collapse='Collapse call flow', running='Running', done='Finished',
               failed='Finished with errors', waiting='Waiting for calls', empty='Calls will appear when you start an operation.',
               login='Sign in with Verify', anonymous='Sign in with Verify to see your session’s call flow.',
               hop='hop', hops='hops', trace='Open trace', pending='In progress…', noResponse='No recorded response',
               finished='Completed', local='Local HTTP lab', scroll='Call diagram for this execution'),
}


def live_snapshot(records, tid, *, busy=False, language='es'):
    """Use build_flow as the sole call classifier, then narrow its public schema.

    No raw attributes, endpoints, identities, RAR/personal data, credentials,
    captured bodies or inspection URLs are sent to this component.
    """
    flow = build_flow(records)
    active = {r['span_id'] for r in records if r.get('active')}
    t = Translator(language)
    calls = [dict(id=c['id'], source='lumen', target=c['target'], title=t(c['title']),
                  active=c['id'] in active,
                  state='running' if c['id'] in active else c['state'],
                  http_status=c['http_status'] if c['id'] not in active and type(c['http_status']) is int else None,
                  duration_ms=None if c['id'] in active else c['duration_ms'],
                  response_recorded=c['id'] not in active and c['response_recorded'])
             for c in flow['calls'] if c['target'] in ACTORS]
    return dict(traceId=tid, authenticated=True, busy=bool(busy or active),
                failed=bool(flow['local_errors'] or any(c['state'] == 'error' for c in calls)),
                actors=[dict(id=a['id'], name=ACTORS[a['id']][0]) for a in flow['actors']], calls=calls)


class LiveCallFlow(Element, component='live_call_flow.js'):
    def __init__(self, session, *, language='es', is_busy=lambda: False, is_current=lambda: True):
        super().__init__()
        self.session = session
        self.is_busy = is_busy
        self.is_current = is_current
        self.language = language
        self._last_key = None
        self._props.update(snapshot={}, panelId=f'lcf-panel-{self.id}', messages=COPY['en' if language == 'en' else 'es'],
                           icons=ICONS, locale=Translator(language).locale)
        ui.add_css((STATIC / 'live_call_flow.css').read_text())
        self.refresh()
        # Idle ticks only check session/trace identity. Rebuild during an action,
        # on a new trace, and once when the operation releases the session lock.
        self.timer = ui.timer(.5, self.refresh)
        # NiceGUI passes the client to callbacks with one parameter; cancel's
        # only parameter is keyword-only, so expose an explicit zero-arg hook.
        self.client.on_delete(lambda: self.timer.cancel())

    def refresh(self):
        session = self.session
        authenticated = bool(session and self.is_current() and session.subject and session.expires_at > time.time())
        tid = session.traces[-1] if authenticated and session.traces else ''
        if not re.fullmatch(r'[0-9a-f]{32}', tid):
            tid = ''
        busy = bool(authenticated and self.is_busy())
        key = (authenticated, tid, busy)
        if key == self._last_key and not busy and not self._props['snapshot'].get('busy'):
            return
        self._last_key = key
        if authenticated:
            snapshot = live_snapshot(records_for({tid}, include_active=True) if tid else [], tid,
                                     busy=busy, language=self.language)
        else:
            snapshot = dict(traceId='', authenticated=False, busy=False, failed=False, actors=[], calls=[])
        if snapshot != self._props['snapshot']:
            self._props['snapshot'] = snapshot
            self.update()


def mount_live_call_flow(session, **options):
    return LiveCallFlow(session, **options)


def lab_http_badge(request, language='es'):
    if request.url.scheme == 'http' and request.url.hostname in {'localhost', '127.0.0.1', '::1'}:
        ui.label(COPY['en' if language == 'en' else 'es']['local']).classes('lumen-lab-badge')
