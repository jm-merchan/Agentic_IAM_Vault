"""Explicit, session-owned replay of captured lab calls. No ambient credentials."""
import asyncio
import json
import re
import time
from urllib.parse import urlsplit

import httpx
import pymysql
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import lab_capture
from .i18n import Translator

LIMIT = 1024 * 1024
TRANSPORT_HEADERS = {'host', 'content-length', 'connection', 'transfer-encoding', 'proxy-authorization',
                     'proxy-connection', 'te', 'trailer', 'upgrade', 'accept-encoding'}


def templates(stored):
    sections = (stored or {}).get('sections', {})
    result = []
    for key, section in sections.items():
        if not key.startswith('http.request.') or section['truncated']:
            continue
        value = section['value']
        if not all(k in value for k in ('method', 'url', 'headers', 'body_text')):
            continue
        result.append(dict(id=key, kind='http', attempt=value.get('attempt', 1),
                           method=value['method'], url=value['url'],
                           headers={k: v for k, v in value['headers'].items() if k.lower() not in TRANSPORT_HEADERS},
                           body=value['body_text']))
    connection, query = sections.get('connection'), sections.get('query')
    if connection and query and not connection['truncated'] and not query['truncated']:
        result.append(dict(id='mysql', kind='mysql', connection=connection['value'],
                           statement=query['value']['statement'], parameters=query['value']['parameters']))
    return result


def origin(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or any(ord(c) < 33 for c in url)):
        raise ValueError('URL no válida.')
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)


def validate_http(template, data):
    method, url, headers, body = (data.get(k) for k in ('method', 'url', 'headers', 'body'))
    if not isinstance(method, str) or method.upper() not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'LIST', 'HEAD', 'OPTIONS'}:
        raise ValueError('Método HTTP no válido.')
    if not isinstance(url, str) or origin(url) != origin(template['url']):
        raise ValueError('La URL debe conservar el protocolo, servidor y puerto de la petición capturada.')
    if not isinstance(headers, dict) or len(headers) > 100:
        raise ValueError('Las cabeceras deben ser un objeto JSON de texto.')
    cleaned = {}
    for key, value in headers.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                or not isinstance(value, str) or any(ord(c) < 32 or ord(c) > 126 for c in value)):
            raise ValueError('Cabecera HTTP no válida.')
        if key.lower() in TRANSPORT_HEADERS:
            continue
        cleaned[key] = value
    if not isinstance(body, str) or len(body.encode()) > LIMIT:
        raise ValueError('El cuerpo supera el límite de 1 MiB o no es texto.')
    return method.upper(), url, cleaned, body.encode('utf-8')


async def execute_http(template, data, *, vault_origin=None, vault_tls=True):
    method, url, headers, body = validate_http(template, data)
    verify = vault_tls if vault_origin and origin(url) == origin(vault_origin) else True
    started = time.monotonic()
    # Fresh client: no cookies, refresh, retries, automatic redirects or privileged auth.
    async with httpx.AsyncClient(verify=verify, timeout=60, follow_redirects=False, trust_env=False) as client:
        async with client.stream(method, url, headers=headers, content=body) as response:
            buffer = bytearray()
            truncated = False
            async for chunk in response.aiter_bytes():
                remaining = LIMIT - len(buffer)
                buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
                    break
            return dict(kind='http', status_code=response.status_code, headers=dict(response.headers),
                        body=bytes(buffer).decode('utf-8', errors='replace'), truncated=truncated,
                        duration_ms=round((time.monotonic() - started) * 1000, 2))


def execute_sql(template, data):
    statement, parameters = data.get('statement'), data.get('parameters')
    if not isinstance(statement, str) or not statement.strip() or len(statement.encode()) > LIMIT:
        raise ValueError('Consulta SQL no válida.')
    if parameters is not None and not isinstance(parameters, (list, dict)):
        raise ValueError('Los parámetros SQL deben ser una lista, un objeto JSON o null.')
    connection = template['connection']
    # Endpoint and login are from this exact step. MySQL enforces the original role.
    started = time.monotonic()
    with pymysql.connect(host=connection['host'], port=connection['port'], database=connection['database'],
                         user=connection['username'], password=connection['password'], connect_timeout=10,
                         read_timeout=20, write_timeout=20, cursorclass=pymysql.cursors.DictCursor,
                         autocommit=False) as conn:
        with conn.cursor() as cursor:
            cursor.execute(statement, parameters)
            rows = cursor.fetchmany(51) if cursor.description else []
            affected = cursor.rowcount
            conn.commit()
            return dict(kind='mysql', rows=rows[:50], affected_rows=affected, truncated=len(rows) > 50,
                        committed=True, duration_ms=round((time.monotonic() - started) * 1000, 2))


def workbench_router(identity, records_for, cookie='lumen_session', *, vault_origin=None, vault_tls=True):
    router = APIRouter()
    running = set()

    @router.post('/traces/{tid}/steps/{sid}/replay')
    async def replay(tid: str, sid: str, request: Request):
        t = Translator('en' if request.headers.get('x-lumen-language') == 'en' else 'es')
        def result(body, status=200):
            if 'message' in body:
                body['message'] = t(body['message'])
            return JSONResponse(json.loads(json.dumps(body, default=str)), status_code=status,
                                headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache',
                                         'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
        session = identity.sessions.get(request.cookies.get(cookie, ''))
        if not session or not session.subject or session.expires_at <= time.time() or tid not in session.traces:
            return result({'message': 'Traza no disponible para esta sesión.'}, 404)
        if not lab_capture.enabled():
            return result({'message': 'La consola requiere el modo laboratorio.'}, 403)
        # Same-origin browser POST plus JSON; a cross-site form cannot invoke a replay.
        try:
            same_origin = origin(request.headers.get('origin', '')) == origin(str(request.base_url))
        except ValueError:
            same_origin = False
        if (not same_origin or request.headers.get('content-type', '').split(';')[0] != 'application/json'
                or request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'):
            return result({'message': 'La petición debe enviarse desde la consola de esta sesión.'}, 403)
        record = next((r for r in records_for({tid}) if r['span_id'] == sid and r['trace_id'] == tid), None)
        if not record:
            return result({'message': 'Paso no disponible en esta traza.'}, 404)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > LIMIT * 2:
                return result({'message': 'La petición supera el límite de tamaño.'}, 413)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return result({'message': 'Petición JSON no válida.'}, 400)
        stored = lab_capture.STORE.get(tid, sid)
        template = next((item for item in templates(stored) if item['id'] == data.get('template_id')), None)
        if not template:
            return result({'message': 'La captura ha caducado, está truncada o no contiene una petición reproducible. Genera una nueva traza.'}, 410)
        lock_key = session.sid
        if lock_key in running:
            return result({'message': 'Ya hay una petición de consola en curso en esta sesión.'}, 409)
        running.add(lock_key)
        try:
            if template['kind'] == 'http':
                response = await execute_http(template, data, vault_origin=vault_origin, vault_tls=vault_tls)
            else:
                response = await asyncio.to_thread(execute_sql, template, data)
            return result(response)
        except ValueError as error:
            return result({'message': str(error)}, 400)
        except (httpx.HTTPError, pymysql.MySQLError, OSError):
            # Do not reflect exception strings: URLs and driver errors can include credentials.
            return result({'message': 'No se pudo completar la petición. Comprueba el destino, la conexión y la vigencia de la credencial.'}, 502)
        finally:
            running.discard(lock_key)

    return router
