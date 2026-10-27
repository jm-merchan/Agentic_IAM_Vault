"""Small, explicit ES/EN catalogue. Locale belongs to a browser/page, never a process."""
from __future__ import annotations

import json
import re
from copy import copy
from pathlib import Path
from string import Formatter

LANGUAGE_COOKIE = 'lumen_language'
EN = json.loads(Path(__file__).with_name('translations_en.json').read_text())


def browser_language(header: str) -> str:
    candidates = []
    for index, item in enumerate(header.split(',')):
        tag, *params = item.strip().lower().split(';')
        quality = 1.0
        try:
            for param in params:
                if param.strip().startswith('q='):
                    quality = float(param.strip()[2:])
        except ValueError:
            continue
        if 0 < quality <= 1 and tag.split('-')[0] in {'es', 'en'}:
            candidates.append((quality, -index, tag.split('-')[0]))
    return max(candidates)[2] if candidates else 'en'


def request_language(request) -> str:
    preference = request.cookies.get(LANGUAGE_COOKIE)
    return preference if preference in {'es', 'en'} else browser_language(request.headers.get('accept-language', ''))


def safe_return_path(path: str) -> str:
    return path if path in {'/', '/solicitud', '/solicitudes', '/laboratorio-rar', '/mi-espacio'} or re.fullmatch(r'/traces/[0-9a-f]{32}(?:\?span=[0-9a-f]{16})?', path) else '/'


# Templates are only matched against authored display text, never capture values.
TEMPLATES = []
for source, target in EN.items():
    if '{' not in source:
        continue
    parts, fields = [], []
    for literal, field, spec, conversion in Formatter().parse(source):
        parts.append(re.escape(literal))
        if field is not None:
            parts.append('(.*?)')
            fields.append(field)
    TEMPLATES.append((re.compile('^' + ''.join(parts) + '$', re.DOTALL), fields, target))


class Translator:
    def __init__(self, language='es'):
        self.language = 'en' if language == 'en' else 'es'
        self.locale = 'en-US' if self.language == 'en' else 'es-ES'

    def __call__(self, text, **values):
        if not isinstance(text, str):
            return text
        translated = text
        if self.language == 'en':
            translated = EN.get(text, text)
            if translated == text and text not in EN:
                for pattern, fields, target in TEMPLATES:
                    match = pattern.fullmatch(text)
                    if match:
                        translated = target.format(**dict(zip(fields, match.groups())))
                        break
        return translated.format(**values) if values else translated

    def props(self, props):
        return re.sub(r'(aria-label|title)="([^"]*)"',
                      lambda match: f'{match[1]}="{self(match[2])}"', props)

    def number(self, value, decimals=4):
        text = f'{value:.{decimals}f}'.rstrip('0').rstrip('.')
        return text.replace('.', ',') if self.language == 'es' else text


def page_language(request, session=None):
    from nicegui import ui
    language = request_language(request)
    # NiceGUI page definitions are shared; clone for this client before selecting
    # Quasar translations and the HTML language. Concurrent pages stay isolated.
    ui.context.client.page = copy(ui.context.client.page)
    ui.context.client.page.language = 'en-US' if language == 'en' else 'es'
    ui.context.client.page.title = 'Lumen · Energy, made clear' if language == 'en' else 'Lumen · Tu energía, con claridad'
    return Translator(language)


def language_switch(request, t, is_busy=lambda: False):
    from nicegui import ui
    from urllib.parse import urlencode
    return_path = request.url.path
    selected_span = request.query_params.get('span', '')
    if re.fullmatch(r'/traces/[0-9a-f]{32}', return_path) and re.fullmatch(r'[0-9a-f]{16}', selected_span):
        return_path += '?' + urlencode({'span': selected_span})
    with ui.element('div').classes('language-switch').props(t.props('role=group aria-label="Idioma"')):
        for code in ('en', 'es'):
            def choose(code=code):
                if is_busy():
                    ui.notify(t('Espera a que termine la operación para cambiar de idioma.'))
                    return
                ui.navigate.to('/language/' + code + '?' + urlencode({'next': return_path}))
            ui.button(code.upper(), color=None, on_click=choose).props(
                f'flat no-caps aria-label="{"English" if code == "en" else "Español"}" aria-pressed="{str(code == t.language).lower()}"'
            ).classes('language-option' + (' language-active' if code == t.language else ''))
