"""OpenTelemetry with opt-in, credential-redacted model and tool content."""
from __future__ import annotations

import functools
import inspect
import json
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

from langchain_core.callbacks import AsyncCallbackHandler
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode
from .trace_content import CURRENT, ContentRecorder, message_document
from .lab_capture import capture
from .rar import LAB_CONTEXT

RECORDS = deque(maxlen=3000)
ACTIVE_SPANS = {}
LOCK = threading.Lock()
TRACE_DIR = Path(os.environ.get('LUMEN_TRACE_DIR', '/tmp/lumen-telemetry'))
TRACE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


class LocalTraceExporter(SpanExporter):
    def export(self, spans):
        records = []
        for s in spans:
            records.append(dict(trace_id=f'{s.context.trace_id:032x}', span_id=f'{s.context.span_id:016x}',
                                parent_id=f'{s.parent.span_id:016x}' if s.parent else None,
                                name=s.name, start_ns=s.start_time, end_ns=s.end_time,
                                duration_ms=round((s.end_time-s.start_time)/1e6, 2),
                                status=s.status.status_code.name, attributes=dict(s.attributes)))
        with LOCK:
            RECORDS.extend(records)
            fd = os.open(TRACE_DIR / 'spans.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'a') as f:
                for record in records:
                    f.write(json.dumps(record) + '\n')
        return SpanExportResult.SUCCESS


class LiveSpanProcessor(SpanProcessor):
    """Keep in-flight spans local; completed exports and trace pages are unchanged."""
    def on_start(self, span, parent_context=None):
        with LOCK:
            ACTIVE_SPANS[span.context.span_id] = span

    def on_end(self, span):
        with LOCK:
            ACTIVE_SPANS.pop(span.context.span_id, None)


PROVIDER = TracerProvider(resource=Resource.create({'service.name': 'lumen-chatbot',
                                                    'deployment.environment.name': 'minikube-lab'}))
PROVIDER.add_span_processor(SimpleSpanProcessor(LocalTraceExporter()))
PROVIDER.add_span_processor(LiveSpanProcessor())
if endpoint := os.environ.get('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT'):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    PROVIDER.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=5),
                                                   schedule_delay_millis=1000))
TRACER = PROVIDER.get_tracer('lumen', '1.0')


def trace_id():
    context = trace.get_current_span().get_span_context()
    return f'{context.trace_id:032x}' if context.is_valid else ''


def headers():
    context = trace.get_current_span().get_span_context()
    return {'traceparent': f'00-{context.trace_id:032x}-{context.span_id:016x}-01'} if context.is_valid else {}


@contextmanager
def span(name, **attributes):
    # Automatic exception capture can leak HTTP bodies, SQL credentials or tool input.
    with TRACER.start_as_current_span(name, attributes={**LAB_CONTEXT.get(), **attributes},
                                     record_exception=False, set_status_on_exception=False) as current:
        try:
            yield current
        except Exception as exc:
            current.set_attribute('error.type', type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR))
            raise


def operation(name):
    def decorate(function):
        def capture_input(current, args, kwargs):
            recorder = CURRENT.get() if name.startswith('tool.') else None
            if recorder:
                current.set_attribute('gen_ai.tool.name', name.removeprefix('tool.'))
                recorder.capture(current, 'gen_ai.tool.call.arguments',
                                 dict(inspect.signature(function).bind(*args, **kwargs).arguments))
            return recorder

        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def wrapped(*args, **kwargs):
                with span(name) as current:
                    recorder = capture_input(current, args, kwargs)
                    result = await function(*args, **kwargs)
                    if recorder:
                        recorder.capture(current, 'gen_ai.tool.call.result', result)
                    return result
        else:
            @functools.wraps(function)
            def wrapped(*args, **kwargs):
                with span(name) as current:
                    recorder = capture_input(current, args, kwargs)
                    result = function(*args, **kwargs)
                    if recorder:
                        recorder.capture(current, 'gen_ai.tool.call.result', result)
                    return result
        return wrapped
    return decorate


def records_for(ids, *, include_active=False):
    with LOCK:
        records = [r for r in RECORDS if r['trace_id'] in ids]
        if include_active:
            completed = {r['span_id'] for r in records}
            now = time.time_ns()
            for current in ACTIVE_SPANS.values():
                tid = f'{current.context.trace_id:032x}'
                sid = f'{current.context.span_id:016x}'
                if tid not in ids or sid in completed:
                    continue
                # Snapshot only. No provisional record enters RECORDS, the log,
                # OTLP or the existing trace/sensitive/replay APIs.
                records.append(dict(trace_id=tid, span_id=sid,
                    parent_id=f'{current.parent.span_id:016x}' if current.parent else None,
                    name=current.name, start_ns=current.start_time, end_ns=now,
                    duration_ms=round((now-current.start_time)/1e6, 2),
                    status=current.status.status_code.name, attributes=dict(current.attributes), active=True))
        return records


class ModelSpans(AsyncCallbackHandler):
    """One span per model invocation. Tool spans come from explicit wrappers."""
    def __init__(self, model, recorder=None, provider='xai', *, credential=None):
        self.model = model
        self.provider = provider
        self.recorder = recorder or ContentRecorder()
        self.sequence = 0
        self.context = trace.set_span_in_context(trace.get_current_span())
        self.active = {}
        self.credential = credential

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.sequence += 1
        current = TRACER.start_span(self.provider + '.chat', context=self.context, attributes={
            'gen_ai.provider.name': self.provider, 'gen_ai.request.model': self.model,
            'agent.identity': 'chatbot-' + self.provider,
            'gen_ai.operation.name': 'chat', 'gen_ai.input.message_count': sum(map(len, messages)),
            'lumen.model.call_index': self.sequence, 'lumen.content.enabled': self.recorder.enabled,
            'lumen.content.source': 'langchain_callback',
        })
        self.active[run_id] = current
        from .http_capture import MODEL_SPANS
        MODEL_SPANS[run_id] = current
        if self.credential:
            capture(current, 'authentication', 'Credencial utilizada por el cliente del modelo', {
                'provider': self.provider, 'model': self.model,
                'Authorization': 'Bearer ' + self.credential,
                'source': 'Credencial entregada al SDK para esta invocación',
            })
        if self.recorder.enabled:
            documents = [message_document(m) for batch in messages for m in batch]
            self.recorder.capture(current, 'gen_ai.input.messages', documents)
            last_user = next((m for m in reversed(documents) if m['role'] == 'user'), None)
            if last_user:
                self.recorder.capture(current, 'lumen.user.message', last_user)
            params = kwargs.get('invocation_params') or {}
            allowed = {'temperature', 'top_p', 'max_tokens', 'max_completion_tokens', 'seed',
                       'stop', 'reasoning_effort', 'tool_choice', 'parallel_tool_calls', 'response_format'}
            self.recorder.capture(current, 'lumen.model.parameters', {k: v for k, v in params.items() if k in allowed})
            definitions = []
            for tool in params.get('tools') or []:
                if isinstance(tool, dict) and tool.get('type') == 'function':
                    definitions.append({'type': 'function', **{k: v for k, v in tool.get('function', {}).items()
                                                             if k in {'name', 'description', 'parameters', 'strict'}}})
            self.recorder.capture(current, 'gen_ai.tool.definitions', definitions)

    async def on_llm_end(self, response, *, run_id, **kwargs):
        from .http_capture import MODEL_SPANS
        MODEL_SPANS.pop(run_id, None)
        current = self.active.pop(run_id, None)
        if current:
            outputs, reasons = [], []
            for row in response.generations:
                for item in row:
                    message = getattr(item, 'message', None)
                    usage = getattr(message, 'usage_metadata', None) or {}
                    for source, target in [('input_tokens', 'input_tokens'), ('output_tokens', 'output_tokens')]:
                        if isinstance(usage.get(source), int):
                            current.set_attribute('gen_ai.usage.' + target, usage[source])
                    for category in ('input_token_details', 'output_token_details'):
                        for key, value in usage.get(category, {}).items():
                            if isinstance(value, int):
                                current.set_attribute('lumen.usage.' + category + '.' + key, value)
                    if message is not None:
                        metadata = message.response_metadata or {}
                        reason = metadata.get('finish_reason') or (item.generation_info or {}).get('finish_reason')
                        if reason:
                            reasons.append(str(reason))
                        for source, target in [('model_name', 'gen_ai.response.model'), ('id', 'gen_ai.response.id')]:
                            if isinstance(metadata.get(source), str):
                                current.set_attribute(target, self.recorder.text(metadata[source]))
                        if self.recorder.enabled:
                            output = message_document(message)
                            if reason:
                                output['finish_reason'] = str(reason)
                            outputs.append(output)
            if reasons:
                current.set_attribute('gen_ai.response.finish_reasons', reasons)
            self.recorder.capture(current, 'gen_ai.output.messages', outputs)
            current.end()

    async def on_llm_error(self, error, *, run_id, **kwargs):
        from .http_capture import MODEL_SPANS
        MODEL_SPANS.pop(run_id, None)
        current = self.active.pop(run_id, None)
        if current:
            current.set_attribute('error.type', type(error).__name__)
            current.set_status(Status(StatusCode.ERROR))
            current.end()

    def close(self):
        for current in self.active.values():
            current.set_attribute('error.type', 'Interrupted')
            current.set_status(Status(StatusCode.ERROR))
            current.end()
        from .http_capture import MODEL_SPANS
        for run_id in self.active:
            MODEL_SPANS.pop(run_id, None)
        self.active.clear()
        self.credential = None
