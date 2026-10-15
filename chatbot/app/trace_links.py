"""Links from the local trace viewer to the provisioned Grafana instance."""
import json
import os
from urllib.parse import urlencode


def grafana_trace_url(tid: str, records: list[dict]) -> str:
    datasource = os.environ.get('LUMEN_GRAFANA_TEMPO_UID', 'lumen-tempo')
    time_range = {'from': 'now-7d', 'to': 'now'}
    if records:
        time_range = {
            'from': str(min(r['start_ns'] for r in records) // 1_000_000 - 60_000),
            'to': str(max(r['end_ns'] for r in records) // 1_000_000 + 60_000),
        }
    panes = {'lumen': {
        'datasource': datasource,
        'queries': [{'refId': 'A', 'queryType': 'traceql', 'query': tid,
                     'datasource': {'type': 'tempo', 'uid': datasource}}],
        'range': time_range,
    }}
    query = urlencode({'schemaVersion': 1, 'orgId': os.environ.get('LUMEN_GRAFANA_ORG_ID', '1'),
                       'panes': json.dumps(panes, separators=(',', ':'))})
    base_url = os.environ.get('LUMEN_GRAFANA_URL', 'http://localhost:3000').rstrip('/')
    return f'{base_url}/explore?{query}'
