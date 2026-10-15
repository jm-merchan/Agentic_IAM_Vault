import json

import pytest

from app.telemetry import headers, records_for, span, trace_id


def test_w3c_context_and_parent_relationship():
    with span('test.parent'):
        tid = trace_id()
        parent = headers()['traceparent'].split('-')[2]
        with span('test.child'):
            child = headers()['traceparent']
            assert child.split('-')[1] == tid
            assert child.split('-')[2] != parent
    records = records_for({tid})
    assert next(r for r in records if r['name'] == 'test.child')['parent_id'] == parent


def test_errors_do_not_export_exception_text_or_stack():
    with pytest.raises(RuntimeError):
        with span('test.failure'):
            tid = trace_id()
            raise RuntimeError('CANARY_SECRET_http_body_password')
    encoded = json.dumps(records_for({tid}))
    assert 'CANARY_SECRET' not in encoded
    assert 'RuntimeError' in encoded
    assert records_for({tid})[0]['status'] == 'ERROR'

