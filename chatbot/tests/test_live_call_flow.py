import json
import time
from types import SimpleNamespace

import pytest

from app.live_call_flow_ui import LiveCallFlow, live_snapshot
from app.telemetry import ACTIVE_SPANS, RECORDS, records_for, span, trace_id


def test_deleting_client_cancels_flow_timer_without_callback_errors(monkeypatch):
    from nicegui import core, ui
    from nicegui.client import Client

    errors = []
    monkeypatch.setattr(core.app, 'handle_exception', errors.append)
    with Client(ui.page('/test-live-flow-cleanup')) as client:
        widget = LiveCallFlow(None)
    client.delete()
    assert not errors
    assert widget.timer._is_canceled


def test_inflight_is_opt_in_and_return_appears_only_after_completion():
    with span('lumen.action'):
        tid = trace_id()
        with span('vault.read', **{'vault.path': 'database/creds/chatbot-readonly'}) as current:
            sid = f'{current.context.span_id:016x}'
            assert records_for({tid}) == []
            snapshot = live_snapshot(records_for({tid}, include_active=True), tid)
            call = snapshot['calls'][0]
            assert call['active'] and call['state'] == 'running'
            assert call['http_status'] is None and call['duration_ms'] is None
            assert not call['response_recorded']
            assert not any(r['span_id'] == sid for r in RECORDS)
            current.set_attribute('http.response.status_code', 200)
        snapshot = live_snapshot(records_for({tid}, include_active=True), tid)
        assert snapshot['busy']  # the surrounding operation is still open
        assert len(snapshot['calls']) == 1
        assert snapshot['calls'][0]['id'] == sid
        assert not snapshot['calls'][0]['active']
        assert snapshot['calls'][0]['http_status'] == 200
        assert current.context.span_id not in ACTIVE_SPANS
    snapshot = live_snapshot(records_for({tid}, include_active=True), tid)
    assert not snapshot['busy']
    assert len(records_for({tid})) == 2


@pytest.mark.parametrize('name,target', [
    ('verify.oidc_login', 'verify'), ('verify.client_credentials', 'verify'),
    ('verify.token_exchange', 'verify'), ('verify.ciba_start', 'verify'), ('verify.ciba_poll', 'verify'),
    ('vault.read', 'vault'), ('vault.write', 'vault'), ('vault.jwks', 'vault'), ('mysql.query', 'mysql'),
    ('openai.token_exchange', 'openai'), ('openai.chat', 'openai'),
    ('anthropic.token_exchange', 'anthropic'), ('anthropic.chat', 'anthropic'),
    ('xai.chat', 'xai'), ('tavily.search', 'tavily'),
])
def test_supported_calls_and_credentials_never_enter_overlay(name, target):
    canary = 'CANARY_PRIVATE_VALUE'
    with span(name, **{'http.response.status_code': 200, 'vault.path': canary,
                      'vault.namespace': canary, 'gen_ai.input.messages': canary,
                      'Authorization': canary, 'client_secret': canary,
                      'approval.id': canary, 'search.topic': canary,
                      'gen_ai.request.model': canary, 'db.namespace': canary,
                      'auth.rar.presented': canary, 'http.request.body': canary}):
        tid = trace_id()
    snapshot = live_snapshot(records_for({tid}), tid, language='en')
    assert len(snapshot['calls']) == 1
    assert snapshot['calls'][0]['target'] == target
    assert canary not in json.dumps(snapshot)
    assert set(snapshot['calls'][0]) == {'id', 'source', 'target', 'title', 'active', 'state',
                                        'http_status', 'duration_ms', 'response_recorded'}


def test_oidc_before_exchange_does_not_invent_a_network_call():
    with span('verify.oidc_login'):
        tid = trace_id()
        assert not live_snapshot(records_for({tid}, include_active=True), tid)['calls']


def test_failure_and_session_scope_with_expiry_and_revocation():
    with span('vault.read', **{'http.response.status_code': 403}):
        own = trace_id()
    with span('openai.chat'):
        other = trace_id()
    session = SimpleNamespace(subject='human', expires_at=time.time() + 60, traces=[own])
    widget = SimpleNamespace(session=session, is_busy=lambda: False, is_current=lambda: True,
                             language='es', _last_key=None, _props={'snapshot': {}}, update=lambda: None)
    LiveCallFlow.refresh(widget)
    assert widget._props['snapshot']['failed']
    assert [c['target'] for c in widget._props['snapshot']['calls']] == ['vault']
    assert other not in json.dumps(widget._props)
    widget.is_current = lambda: False
    LiveCallFlow.refresh(widget)
    assert widget._props['snapshot']['calls'] == []
    assert not widget._props['snapshot']['authenticated']
    widget.is_current = lambda: True
    session.expires_at = 0
    LiveCallFlow.refresh(widget)
    assert not widget._props['snapshot']['authenticated']


def test_new_trace_clears_previous_calls_before_first_completed_span():
    with span('mysql.query'):
        first = trace_id()
    session = SimpleNamespace(subject='human', expires_at=time.time() + 60, traces=[first])
    widget = SimpleNamespace(session=session, is_busy=lambda: False, is_current=lambda: True,
                             language='es', _last_key=None, _props={'snapshot': {}}, update=lambda: None)
    LiveCallFlow.refresh(widget)
    assert widget._props['snapshot']['calls']
    with span('lumen.action'):
        session.traces.append(trace_id())
        LiveCallFlow.refresh(widget)
        assert widget._props['snapshot']['calls'] == []
        assert widget._props['snapshot']['busy']
    LiveCallFlow.refresh(widget)
    assert not widget._props['snapshot']['busy']
