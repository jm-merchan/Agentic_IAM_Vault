"""Session-scoped, on-demand inspection of laboratory call evidence."""
import base64
import json
import time

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import lab_capture
from .request_workbench import templates
from .i18n import Translator, request_language

RAW_TITLES = {
    'gen_ai.input.messages': 'Mensajes enviados al modelo · telemetría',
    'gen_ai.output.messages': 'Respuesta del modelo · telemetría',
    'gen_ai.tool.definitions': 'Herramientas ofrecidas al modelo',
    'lumen.model.parameters': 'Parámetros del modelo',
    'lumen.user.message': 'Pregunta del usuario',
    'vault.http.request': 'Petición enviada a Vault',
    'vault.http.response': 'Respuesta recibida de Vault',
    'vault.auth.jwt': 'Token presentado a Vault',
    'vault.auth.jwt.decoded': 'Token de Vault · decodificado',
    'spiffe.jwt_svid': 'JWT-SVID emitido',
    'spiffe.jwt_svid.decoded': 'JWT-SVID · validación registrada',
    'openai.exchange.subject_token': 'JWT-SVID enviado a OpenAI',
    'anthropic.exchange.assertion': 'JWT-SVID enviado a Claude',
}


def inspect_record(record, stored=None):
    sections = list((stored or {}).get('sections', {}).values())
    attrs = record.get('attributes', {})
    for key, title in RAW_TITLES.items():
        if key not in attrs:
            continue
        try:
            value = json.loads(attrs[key])
        except (ValueError, TypeError):
            continue
        sections.append(dict(key=key, title=title, value=value, source='span',
                             truncated=bool(attrs.get(key + '.truncated'))))

    # Derive only from values actually captured in this span. Never match by time
    # or borrow credentials from another operation, trace or session.
    derived, seen = [], set()

    def walk(value, path, depth=0):
        if depth > 20:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + '.' + key, depth + 1)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f'{path}[{index}]', depth + 1)
        elif isinstance(value, str):
            token = value.removeprefix('Bearer ')
            if token.count('.') == 2 and token.startswith('eyJ') and token not in seen:
                try:
                    decoded = {'header': jwt.get_unverified_header(token),
                               'claims': jwt.decode(token, options={'verify_signature': False}),
                               'signature_verified_by_decoder': False}
                except jwt.InvalidTokenError:
                    return
                seen.add(token)
                derived.append(dict(key='decoded.' + path, title='JWT decodificado · ' + path,
                                    value=decoded, source='derived', truncated=False))
            if path.endswith('.plaintext'):
                try:
                    plaintext = base64.b64decode(value, validate=True).decode('utf-8')
                except (ValueError, UnicodeError):
                    return
                derived.append(dict(key='plaintext.' + path, title='Texto en claro · ' + path,
                                    value=plaintext, source='derived', truncated=False))

    for section in sections:
        if not section['truncated']:
            walk(section['value'], section['key'])
    return sections + derived


def inspection_router(identity, records_for, cookie='lumen_session'):
    router = APIRouter()

    @router.get('/traces/{tid}/steps/{sid}/sensitive')
    def sensitive(tid: str, sid: str, request: Request):
        language = request.headers.get("x-lumen-language")
        t = Translator(language if language in {"es", "en"} else request_language(request))
        def result(body, status=200):
            body = localize_inspection(body, t)
            return JSONResponse(body, status_code=status, headers={
                'Cache-Control': 'no-store', 'Pragma': 'no-cache',
                'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
            })

        session = identity.sessions.get(request.cookies.get(cookie, ''))
        if (not session or not session.subject or session.expires_at <= time.time()
                or tid not in session.traces):
            return result({'message': 'Traza no disponible para esta sesión.'}, 404)
        if not lab_capture.enabled():
            return result({'message': 'La captura sensible está desactivada. Activa el modo laboratorio y genera una nueva traza.'}, 403)
        record = next((r for r in records_for({tid}) if r['span_id'] == sid and r['trace_id'] == tid), None)
        if not record:
            return result({'message': 'Paso no disponible en esta traza.'}, 404)
        stored = lab_capture.STORE.get(tid, sid)
        sections = inspect_record(record, stored)
        return result({
            'span_id': sid, 'sections': sections, 'requests': templates(stored),
            'expires_at': min(session.expires_at, (stored or {}).get('expires_at', time.time() + 600)),
            'message': '' if sections else 'No hay valores capturados para este paso. Genera una nueva traza; las capturas en memoria caducan a los 10 minutos o al reiniciar Lumen.',
            'note': 'Valores de esta ejecución. La decodificación de JWT no verifica su firma. Los valores en memoria caducan a los 10 minutos; los intercambios raw de Vault/SPIFFE conservan la retención de las trazas.',
        })

    return router


def localize_inspection(body, t):
    """Translate only UI captions. Evidence values are never rewritten."""
    result = dict(body)
    for key in ('message', 'note'):
        if key in result:
            result[key] = t(result[key])
    if 'sections' in result:
        result['sections'] = [dict(section, title=t(section['title'])) for section in result['sections']]
    return result
