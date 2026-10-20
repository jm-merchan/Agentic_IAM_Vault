import base64
from pathlib import Path

from nicegui import ui
from nicegui.element import Element

from .trace_flow import build_flow
from .lab_capture import enabled
from .i18n import EN, Translator

ICON_DIR = Path(__file__).parents[1] / 'static/service-icons'
ICONS = {
    path.stem: f'data:image/{"svg+xml" if path.suffix == ".svg" else "png"};base64,'
    + base64.b64encode(path.read_bytes()).decode('ascii')
    for path in ICON_DIR.iterdir() if path.suffix in {'.svg', '.png'}
}


class TraceFlow(Element, component='trace_flow.js'):
    def __init__(self, records: list[dict], trace_id='', language='es'):
        super().__init__()
        self._props['flow'] = localize_flow(build_flow(records), language)
        self._props['messages'] = EN if language == 'en' else {}
        self._props['locale'] = Translator(language).locale
        self._props['traceId'] = trace_id
        self._props['labEnabled'] = enabled()
        self._props['icons'] = {actor['id']: ICONS[actor['id']]
                                for actor in self._props['flow']['actors'] if actor['id'] in ICONS}
        ui.add_css((Path(__file__).parents[1] / 'static/trace_flow.css').read_text())


def localize_flow(flow, language='es'):
    """Keep IDs, names, routes, context and timing intact; translate display copy."""
    from copy import deepcopy
    result = deepcopy(flow)
    t = Translator(language)
    result['title'] = t(result['title'])
    for actor in result['actors']:
        actor['description'] = t(actor['description'])
    for item in result['calls'] + result['local']:
        for key in ('title', 'status', 'request', 'credential', 'response'):
            if key in item:
                item[key] = t(item[key])
        if 'notes' in item:
            item['notes'] = [t(note) for note in item['notes']]
        # SDK endpoint combines a model ID with an authored display caption.
        if item.get('method') == 'SDK':
            item['endpoint'] = t(item['endpoint'])
    return result
