"""Capture the actual HTTP payload, tied to one call, without changing its stream."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from uuid import uuid4

import httpx
import httpx2
from opentelemetry import trace
from . import lab_capture

MODEL_SPANS = {}
MODEL_CALL = ContextVar('lumen_model_http_call', default=None)
MODEL_RUN = ContextVar('lumen_model_run_id', default=None)


def body_document(raw, content_type=''):
    text = raw.decode('utf-8', errors='replace')
    try:
        return text, json.loads(text)
    except ValueError:
        from urllib.parse import parse_qs
        if content_type.startswith('application/x-www-form-urlencoded'):
            return text, {k: v[0] if len(v) == 1 else v for k, v in parse_qs(text, keep_blank_values=True).items()}
        return text, text


def record_request(current, request):
    if not lab_capture.enabled() or not current.get_span_context().is_valid:
        return None
    context = current.get_span_context()
    stored = lab_capture.STORE.get(f'{context.trace_id:032x}', f'{context.span_id:016x}') or {}
    attempt = 1 + sum(k.startswith('http.request.') for k in stored.get('sections', {}))
    text, body = body_document(request.content, request.headers.get('content-type', ''))
    lab_capture.capture(current, f'http.request.{attempt}', f'Petición HTTP real · intento {attempt}', {
        'method': request.method, 'url': str(request.url), 'headers': dict(request.headers),
        'body_text': text, 'body': body, 'attempt': attempt,
    })
    current.set_attribute('lumen.http.attempts', attempt)
    current.set_attribute('http.request.method', request.method)
    current.set_attribute('server.address', request.url.host)
    current.set_attribute('url.path', request.url.path)
    return attempt


def record_response(current, response, attempt, raw=None, truncated=False, complete=True):
    if not attempt:
        return
    text, body = body_document(response.content if raw is None else raw, response.headers.get('content-type', ''))
    current.set_attribute('http.response.status_code', response.status_code)
    lab_capture.capture(current, f'http.response.{attempt}', f'Respuesta HTTP real · intento {attempt}', {
        'status_code': response.status_code, 'headers': dict(response.headers),
        'body_text': text, 'body': body, 'truncated': truncated, 'complete': complete,
    })


async def request_hook(request):
    current = MODEL_CALL.get() or MODEL_SPANS.get(MODEL_RUN.get()) or trace.get_current_span()
    try:
        attempt = record_request(current, request)
        if attempt:
            request.extensions['lumen_capture'] = (current, attempt)
    except (ValueError, TypeError, httpx.RequestNotRead, httpx2.RequestNotRead):
        pass


class ResponseStream(httpx.AsyncByteStream, httpx2.AsyncByteStream):
    def __init__(self, original, current, response, attempt):
        self.original, self.current, self.response, self.attempt = original, current, response, attempt
        self.raw, self.truncated, self.complete, self.saved = bytearray(), False, False, False
        self.started = False

    async def __aiter__(self):
        first = not self.started
        self.started = True
        try:
            async for chunk in self.original:
                if first:
                    remaining = max(0, lab_capture.STORE.max_bytes - len(self.raw))
                    self.raw.extend(chunk[:remaining])
                    self.truncated |= len(chunk) > remaining
                yield chunk
            self.complete = True
        finally:
            self.save()

    def save(self):
        if not self.saved:
            self.saved = True
            # These clients request identity encoding, so raw stream bytes are text.
            record_response(self.current, self.response, self.attempt, bytes(self.raw), self.truncated, self.complete)

    async def aclose(self):
        try:
            await self.original.aclose()
        finally:
            self.save()


async def response_hook(response):
    binding = response.request.extensions.get('lumen_capture')
    if not binding:
        return
    current, attempt = binding
    current.set_attribute('http.response.status_code', response.status_code)
    if response.is_stream_consumed:
        record_response(current, response, attempt)
    else:
        response.stream = ResponseStream(response.stream, current, response, attempt)


def model_http_client(*, http_module=httpx, **kwargs):
    # Preserve streaming delivery. Identity encoding makes capture byte-for-byte
    # readable without buffering an entire streamed response before the SDK sees it.
    return http_module.AsyncClient(timeout=60, headers={'Accept-Encoding': 'identity'},
                             event_hooks={'request': [request_hook], 'response': [response_hook]}, **kwargs)


@contextmanager
def bind_model_call(run_manager):
    current = MODEL_SPANS.get(getattr(run_manager, 'run_id', None)) or MODEL_CALL.get()
    token = MODEL_CALL.set(current)
    try:
        yield
    finally:
        MODEL_CALL.reset(token)


class CapturedModelMixin:
    async def astream(self, input, config=None, **kwargs):
        # BaseChatModel.astream does not pass run_manager to _astream. Assign the
        # public run ID before callbacks execute, keeping concurrent streams apart.
        config = dict(config or {})
        config['run_id'] = config.get('run_id') or uuid4()
        token = MODEL_RUN.set(config['run_id'])
        try:
            async for chunk in super().astream(input, config=config, **kwargs):
                yield chunk
        finally:
            MODEL_RUN.reset(token)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        with bind_model_call(run_manager):
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        with bind_model_call(run_manager):
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk


async def close_model_http(model):
    client = getattr(model, 'http_async_client', None)
    if isinstance(client, httpx.AsyncClient):
        await client.aclose()
    client = model.__dict__.get('_async_client')
    if client is not None and type(client).__module__.startswith('anthropic'):
        await client.close()
