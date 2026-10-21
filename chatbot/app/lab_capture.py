"""Opt-in, bounded runtime evidence. Never attached to telemetry or tool results."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict

import httpx
from opentelemetry import trace


def enabled():
    return os.environ.get('LUMEN_TRACE_VAULT_RAW', '0').lower() in {'1', 'true', 'yes'}


class CaptureStore:
    def __init__(self, *, ttl=600, capacity=500, max_bytes=1048576, max_total_bytes=33554432):
        self.ttl, self.capacity, self.max_bytes = ttl, capacity, max_bytes
        self.max_total_bytes = max_total_bytes
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def _purge(self, now):
        for key in list(self.entries):
            if self.entries[key]['expires_at'] <= now:
                del self.entries[key]

    def put(self, trace_id, span_id, key, title, value):
        encoded = json.dumps(value, ensure_ascii=False)
        size = len(encoded.encode('utf-8'))
        truncated = size > self.max_bytes
        if truncated:
            encoded = json.dumps({'_truncated': True,
                                  'preview': encoded.encode('utf-8')[:self.max_bytes // 4].decode('utf-8', 'ignore')},
                                 ensure_ascii=False)
        with self.lock:
            now = time.time()
            self._purge(now)
            entry = self.entries.setdefault((trace_id, span_id),
                                            {'expires_at': now + self.ttl, 'sections': {}})
            entry['sections'][key] = dict(key=key, title=title, value=json.loads(encoded),
                                          truncated=truncated, original_bytes=size, stored_bytes=len(encoded.encode('utf-8')), source='runtime')
            # Bound the whole store as well as each field.
            while len(self.entries) > self.capacity or sum(
                section.get('stored_bytes', 0) for item in self.entries.values()
                for section in item['sections'].values()) > self.max_total_bytes:
                self.entries.popitem(last=False)

    def get(self, trace_id, span_id):
        with self.lock:
            self._purge(time.time())
            entry = self.entries.get((trace_id, span_id))
            return json.loads(json.dumps(entry)) if entry else None


STORE = CaptureStore()


def capture(current, key, title, value):
    if not enabled():
        return
    context = (current or trace.get_current_span()).get_span_context()
    if not context.is_valid:
        return
    try:
        STORE.put(f'{context.trace_id:032x}', f'{context.span_id:016x}', key, title, value)
    except (TypeError, ValueError, RecursionError):
        # Observability must not change the business operation or log the value.
        pass


def request(current, method, url, body, *, basic_auth=None, headers=None):
    if not enabled():
        return
    request_headers = dict(headers or {})
    authentication = {}
    if basic_auth is not None:
        client_id, client_secret = basic_auth
        # Use HTTPX's own encoder, including its UTF-8 handling, just as the
        # actual request does. Capture both the wire header and readable values.
        authorized = next(httpx.BasicAuth(*basic_auth).auth_flow(httpx.Request(method, url)))
        request_headers['Authorization'] = authorized.headers['Authorization']
        authentication = {'scheme': 'HTTP Basic', 'client_id': client_id, 'client_secret': client_secret}
        capture(current, 'authentication', 'Autenticación HTTP Basic', {
            **authentication, 'Authorization': request_headers['Authorization'],
        })
    capture(current, 'request', 'Petición enviada', {
        'method': method, 'url': url, 'headers': request_headers, 'body': body,
        **({'client_id': authentication['client_id'], 'authentication': authentication}
           if authentication else {}),
    })


def response(current, result):
    if not enabled():
        return
    from .http_capture import record_request, record_response
    binding = result.request.extensions.get('lumen_capture')
    attempt = binding[1] if binding else record_request(current, result.request)
    record_response(current, result, attempt)
    try:
        body = result.json()
    except ValueError:
        body = result.text
    capture(current, 'response', 'Respuesta recibida', {'status_code': result.status_code, 'body': body})
