"""Explain recorded Vault decisions without evaluating ACLs or exposing audit bodies."""
from __future__ import annotations

import json
import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


LIMIT = 200
MODES = {
    'obo': ('Delegación OBO', 'Permisos del usuario ∩ techo del agente ∩ RAR, cuando se aplica'),
    'oauth': ('Identidad OAuth', 'Políticas de la identidad ∩ RAR, cuando se aplica'),
    'native': ('Token nativo de Vault', 'Políticas y restricciones del token y de su identidad'),
    'root': ('Token root de Vault', 'Acceso privilegiado de root; no equivale a una evaluación ACL ordinaria'),
    'login': ('Autenticación en Vault', 'Validación del método de autenticación antes de emitir una credencial'),
    'public': ('Claves públicas', 'Ruta pública; no requiere un token para obtener las JWKS'),
    'unknown': ('Identidad no determinada', 'La lógica depende de la autenticación y de los controles aplicables'),
}


def text_value(value):
    return value[:512] if isinstance(value, str) and not value.startswith('hmac-sha256:') else ''


def rar_projection(value):
    """Parameter values can contain plaintext or ciphertext; expose only their names."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    items = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        projected = {k: text_value(item.get(k)) for k in ('type', 'path')}
        projected['capabilities'] = [text_value(c) for c in item.get('capabilities', [])[:20]
                                     if isinstance(c, str)] if isinstance(item.get('capabilities'), list) else []
        for key in ('allowed_parameters', 'denied_parameters', 'required_parameters'):
            params = item.get(key)
            if isinstance(params, (dict, list)):
                projected[key] = [text_value(k) for k in list(params)[:50] if isinstance(k, str)]
        items.append(projected)
    return items


def request_context(record):
    attrs = record.get('attributes', {})
    return (attrs.get('vault.path') or ('spiffe/.well-known/keys' if record['name'] == 'vault.jwks' else ''),
            attrs.get('vault.namespace', 'verify').strip('/'))


async def query_audit(record, loki_url):
    tid, sid = record['trace_id'], record['span_id']
    # IDs originate in the session-owned record, never in a user-supplied query.
    if not re.fullmatch('[0-9a-f]{32}', tid) or not re.fullmatch('[0-9a-f]{16}', sid):
        return [], 'missing'
    needle = f'00-{tid}-{sid}-'
    request_id = record.get('attributes', {}).get('vault.request_id', '')
    if re.fullmatch('[0-9a-f-]{36}', request_id):
        needle += '|' + request_id
    params = {'query': '{service="vault-audit"} |~ ' + json.dumps(needle),
              'start': str(max(0, record['start_ns'] - 5_000_000_000)),
              'end': str(record['end_ns'] + 5_000_000_000), 'limit': LIMIT, 'direction': 'forward'}
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
            # Streaming bounds memory even if an upstream ignores the line limit.
            async with client.stream('GET', loki_url.rstrip('/') + '/loki/api/v1/query_range', params=params) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 4_000_000:
                        return [], 'limited'
        document = json.loads(content)
        if not isinstance(document, dict) or document.get('status') != 'success':
            return [], 'unavailable'
        lines = [line for stream in document['data']['result'] for _, line in stream['values']]
        if len(lines) >= LIMIT:
            return [], 'limited'
        events = []
        for line in lines:
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
            except ValueError:
                continue
        return events, 'available'
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return [], 'unavailable'


def matched_events(record, events):
    """Correlate both IDs and the recorded route; never join by proximity alone."""
    path, namespace = request_context(record)
    prefix = f'00-{record["trace_id"]}-{record["span_id"]}-'
    rid = record.get('attributes', {}).get('vault.request_id')
    grouped = {}
    for event in events:
        req = event.get('request') or {}
        if event.get('type') not in ('request', 'response') or not req.get('id'):
            continue
        if req.get('path') != path or (req.get('namespace') or {}).get('path', '').strip('/') != namespace:
            continue
        parents = (req.get('headers') or {}).get('traceparent', [])
        if isinstance(parents, str):
            parents = [parents]
        if not (any(isinstance(p, str) and re.fullmatch(re.escape(prefix) + '[0-9a-f]{2}', p) for p in parents)
                or (rid and req['id'] == rid)):
            continue
        grouped.setdefault(req['id'], []).append(event)
    # The standby's forwarding attempt is a separate audit request, not the result.
    grouped = {rid: items for rid, items in grouped.items() if not any(
        e.get('type') == 'response' and e.get('error') == 'please forward to the active node' for e in items)}
    if len(grouped) != 1:
        return [], 'ambiguous' if grouped else 'missing'
    items = next(iter(grouped.values()))
    decisions = {(e.get('auth') or {}).get('policy_results', {}).get('allowed') for e in items if e.get('auth')}
    if True in decisions and False in decisions:
        return [], 'ambiguous'
    selected = []
    for kind in ('request', 'response'):
        copies = [e for e in items if e['type'] == kind]
        if copies:
            # Prefer an authenticated copy; protected audit retains decision metadata.
            copies.sort(key=lambda e: (bool(e.get('auth')), bool((e.get('auth') or {}).get('metadata'))), reverse=True)
            decisions = {(e.get('auth') or {}).get('policy_results', {}).get('allowed') for e in copies if e.get('auth')}
            if True in decisions and False in decisions:
                return [], 'ambiguous'
            selected.append(copies[0])
    return selected, 'matched'


def explain(record, events=(), availability='available'):
    attrs = record.get('attributes', {})
    path, namespace = request_context(record)
    matched, state = matched_events(record, events) if availability == 'available' else ([], availability)
    request = next((e for e in matched if e['type'] == 'request'), {})
    response = next((e for e in matched if e['type'] == 'response'), {})
    auth = request.get('auth') or response.get('auth') or {}
    metadata = auth.get('metadata') or {}
    policy_result = auth.get('policy_results') or {}
    allowed = policy_result.get('allowed') if type(policy_result.get('allowed')) is bool else None
    rar = rar_projection(metadata.get('jwt_authorization_details', metadata.get('enterprise_token_authorization_details')))
    actor = text_value(metadata.get('actor_entity_name')) or text_value(metadata.get('actor_entity_id'))
    entity = text_value(auth.get('entity_id'))
    mode = 'unknown'
    if path.startswith('auth/') and path.endswith('/login'):
        mode = 'login'
    elif record['name'] == 'vault.jwks':
        mode = 'public'
    elif actor:
        mode = 'obo'
    elif any(k in metadata for k in ('jwt_issuer', 'enterprise_token_issuer', 'jwt_authorization_details', 'enterprise_token_authorization_details')):
        mode = 'oauth'
    elif 'root' in auth.get('policies', []):
        mode = 'root'
    elif auth or attrs.get('auth.flow') == 'ciba_jwt':
        mode = 'native'
    code = attrs.get('http.response.status_code')
    if allowed is False:
        decision = 'Vault registró una denegación de políticas. El registro no identifica por separado qué capa o regla la causó.'
    elif allowed is True:
        decision = 'Vault registró una evaluación de políticas permitida. El resultado de la operación se comprueba también en la respuesta HTTP.'
    elif code == 403:
        decision = 'La llamada recibió HTTP 403. Sin un resultado de políticas correlacionado no se puede atribuir la causa a usuario, agente o RAR.'
    else:
        decision = 'El estado HTTP describe la respuesta; no desglosa por sí solo la evaluación de autorización.'
    grants = [{'name': text_value(p.get('name')), 'namespace': text_value(p.get('namespace_path'))}
              for p in policy_result.get('granting_policies', []) if isinstance(p, dict) and text_value(p.get('name'))]
    evidence = {
        'request_id': text_value((request or response).get('request', {}).get('id')),
        'recorded_at': text_value((request or response).get('time')),
        'operation': text_value((request or response).get('request', {}).get('operation')),
        'entity_id': entity, 'actor': actor,
        'policies': [text_value(p) for p in auth.get('policies', []) if isinstance(p, str)],
        'granting_policies': grants, 'authorization_details': rar,
        'policy_allowed': allowed, 'request_recorded': bool(request), 'response_recorded': bool(response),
        'error_recorded': bool(response.get('error')),
    }
    return {'mode': mode, 'mode_label': MODES[mode][0], 'logic': MODES[mode][1],
            'audit_state': state, 'path': path, 'namespace': namespace, 'http_status': code,
            'decision': decision, 'evidence': evidence,
            'note': 'La lógica describe los controles aplicables; no es una traza interna del motor ACL. No se consultan políticas actuales para explicar una petición histórica.'}


def decision_router(identity, records_for, cookie='lumen_session', *, loki_url='http://127.0.0.1:3100'):
    router = APIRouter()

    @router.get('/traces/{tid}/steps/{sid}/vault-decision')
    async def decision(tid: str, sid: str, request: Request):
        def result(body, status=200):
            return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store',
                'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})

        session_id = request.cookies.get(cookie, '')
        session = identity.sessions.get(session_id)
        def authorized():
            return (session is not None and identity.sessions.get(session_id) is session
                    and session.subject and session.expires_at > time.time() and tid in session.traces)
        if not authorized():
            return result({'message': 'Traza no disponible para esta sesión.'}, 404)
        record = next((r for r in records_for({tid}) if r['span_id'] == sid and r['trace_id'] == tid), None)
        if not record or record['name'] not in {'vault.read', 'vault.write', 'vault.jwks'}:
            return result({'message': 'Paso de Vault no disponible en esta traza.'}, 404)
        events, state = await query_audit(record, loki_url)
        if not authorized():
            return result({'message': 'Traza no disponible para esta sesión.'}, 404)
        return result(explain(record, events, state))

    return router
