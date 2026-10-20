"""Opt-in conversation capture, sanitized before any telemetry exporter sees it."""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar

REDACTED = '[REDACTED]'
VAULT_CONTENT_KEYS = {'vault.http.request', 'vault.http.response', 'vault.auth.jwt', 'vault.auth.jwt.decoded'}
SPIFFE_CONTENT_KEYS = {'spiffe.jwt_svid', 'spiffe.jwt_svid.decoded', 'openai.exchange.subject_token', 'anthropic.exchange.assertion'}
CONTENT_KEYS = {
    'gen_ai.input.messages', 'gen_ai.output.messages', 'gen_ai.tool.definitions',
    'gen_ai.tool.call.arguments', 'gen_ai.tool.call.result',
    'lumen.model.parameters', 'lumen.user.message',
} | VAULT_CONTENT_KEYS | SPIFFE_CONTENT_KEYS
CURRENT = ContextVar('lumen_trace_content', default=None)
SENSITIVE_KEY = re.compile(r'(^|[_-])(password|passwd|secret|token|api[_-]?key|authorization|cookie|verifier)$', re.I)
TOKEN_PATTERN = re.compile(r'\b(?:eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?:xai-|sk-|tvly-|hvs\.|hvb\.|hvr\.)[A-Za-z0-9_.-]{8,})')
ASSIGNMENT = re.compile(r'''(?ix)(["']?(?:password|passwd|client_secret|session_secret|api[_-]?key|access_token|refresh_token|id_token|x-vault-token)["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')


def sensitive_key(key):
    normalized = re.sub(r'([a-z])([A-Z])', r'\1_\2', str(key))
    return bool(SENSITIVE_KEY.search(normalized))


def config_secrets(value):
    """Extract only credential values, never serialize the application config."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if sensitive_key(key) and isinstance(item, str) and item:
                found.append(item)
            elif isinstance(item, (dict, list)):
                found.extend(config_secrets(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(config_secrets(item))
    return found


class ContentRecorder:
    def __init__(self, secrets=()):
        self.enabled = os.environ.get('LUMEN_TRACE_CONTENT', '0').lower() in {'1', 'true', 'yes'}
        # Bound each JSON attribute below Tempo's explicitly configured 128 KiB limit.
        self.max_bytes = max(1024, min(int(os.environ.get('LUMEN_TRACE_CONTENT_MAX_BYTES', '65536')), 65536))
        self.secrets = tuple(sorted({s for s in secrets if isinstance(s, str) and len(s) >= 6}, key=len, reverse=True))

    def text(self, value):
        for secret in self.secrets:
            value = value.replace(secret, REDACTED)
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', REDACTED, value, flags=re.S)
        value = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/_.=-]+', r'\1 ' + REDACTED, value)
        value = TOKEN_PATTERN.sub(REDACTED, value)
        value = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1' + REDACTED + '@', value)
        return ASSIGNMENT.sub(lambda m: m[1] + REDACTED, value)

    def sanitize(self, value, depth=0):
        if depth > 24:
            return '[OMITTED: nesting limit]'
        if isinstance(value, str):
            # Tool results and arguments often arrive as serialized JSON strings.
            if value.lstrip().startswith(('{', '[')):
                try:
                    parsed = json.loads(value)
                except (ValueError, RecursionError):
                    pass
                else:
                    return json.dumps(self.sanitize(parsed, depth + 1), ensure_ascii=False)
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(k)): REDACTED if sensitive_key(k) else self.sanitize(v, depth + 1)
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize(v, depth + 1) for v in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        # No repr() of arbitrary SDK objects, which can contain credentials.
        return '[OMITTED: ' + type(value).__name__ + ']'

    def capture(self, current, key, value):
        if not self.enabled:
            return
        try:
            cleaned = self.sanitize(value)
            encoded = json.dumps(cleaned, ensure_ascii=False)
            original = len(encoded.encode('utf-8'))
            truncated = original > self.max_bytes
            if truncated:
                # Keep valid JSON and explicit truncation, rather than a broken JSON prefix.
                preview = encoded.encode('utf-8')[:self.max_bytes // 2].decode('utf-8', errors='ignore')
                encoded = json.dumps({'_truncated': True, 'preview': preview}, ensure_ascii=False)
                while len(encoded.encode('utf-8')) > self.max_bytes:
                    preview = preview[:len(preview) // 2]
                    encoded = json.dumps({'_truncated': True, 'preview': preview}, ensure_ascii=False)
            current.set_attribute(key, encoded)
            current.set_attribute(key + '.truncated', truncated)
            current.set_attribute(key + '.original_bytes', original)
            current.set_attribute(key + '.captured_bytes', len(encoded.encode('utf-8')))
        except Exception as exc:
            current.set_attribute('lumen.content.capture_error', type(exc).__name__)


class VaultTraceRecorder(ContentRecorder):
    """Explicit lab mode: retain raw agent/Vault exchanges, including credentials.

    Independent of LLM capture; Vault I/O and the explicit SPIFFE exchange use it.
    """
    def __init__(self):
        super().__init__()
        self.enabled = os.environ.get('LUMEN_TRACE_VAULT_RAW', '0').lower() in {'1', 'true', 'yes'}

    def sanitize(self, value, depth=0):
        return value

    def capture(self, current, key, value):
        if key not in VAULT_CONTENT_KEYS | SPIFFE_CONTENT_KEYS:
            raise ValueError('Raw capture is limited to the agent/Vault exchange')
        super().capture(current, key, value)


@contextmanager
def content_scope(recorder):
    token = CURRENT.set(recorder)
    try:
        yield
    finally:
        CURRENT.reset(token)


def message_document(message):
    """Normalize LangChain messages; don't capture opaque reasoning or binary blocks."""
    role = {'human': 'user', 'ai': 'assistant'}.get(message.type, message.type)
    parts = []
    content = message.content
    if isinstance(content, str):
        if role == 'tool':
            parts.append({'type': 'tool_call_response', 'id': message.tool_call_id, 'result': content})
        elif content:
            parts.append({'type': 'text', 'content': content})
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append({'type': 'text', 'content': block})
            elif isinstance(block, dict) and block.get('type') in {'text', 'output_text', 'input_text'}:
                parts.append({'type': 'text', 'content': block.get('text', '')})
            else:
                parts.append({'type': 'text', 'content': '[OMITTED: non-text block]'})
    for call in getattr(message, 'tool_calls', []):
        parts.append({'type': 'tool_call', 'id': call.get('id', ''), 'name': call.get('name', ''),
                      'arguments': call.get('args', {})})
    result = {'role': role, 'parts': parts}
    if message.name:
        result['name'] = message.name
    return result
