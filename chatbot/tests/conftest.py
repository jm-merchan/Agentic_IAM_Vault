"""Keep synthetic unit-test spans out of the running demo's telemetry."""
import os
import tempfile


_traces = tempfile.TemporaryDirectory(prefix='lumen-unit-traces-')
os.environ['LUMEN_TRACE_DIR'] = _traces.name
os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', None)


def pytest_sessionfinish(session, exitstatus):
    _traces.cleanup()
