"""Keep authoritative events when a Vault standby also audits forwarding."""
import json
from pathlib import Path
import subprocess
import unittest


FILTER = Path(__file__).resolve().parents[1] / 'scripts/normalize-vault-audit.jq'


def event(kind, token=None, request_id='operation', error=None):
    record = {'type': kind, 'request': {'id': request_id}, 'auth': None}
    if token is not None:
        record['auth'] = {'client_token': token}
    if error is not None:
        record['error'] = error
    return record


def normalize(streams):
    payload = {'data': {'result': [
        {'stream': {'audit_mode': mode},
         'values': [[str(i), json.dumps(record)] for i, record in enumerate(records)]}
        for mode, records in streams
    ]}}
    result = subprocess.run(['jq', '-f', str(FILTER)], input=json.dumps(payload),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class AuditNormalizationTests(unittest.TestCase):
    def test_authenticated_raw_copy_wins_in_either_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                records = [event('request', 'synthetic-jwt'), event('request'),
                           event('response', 'synthetic-jwt'), event('response')]
                if reverse:
                    records.reverse()
                result = normalize([('raw', records)])
                self.assertEqual(len(result), 2)
                self.assertEqual({r['type'] for r in result}, {'request', 'response'})
                self.assertTrue(all(r['auth']['client_token'] == 'synthetic-jwt' for r in result))

    def test_raw_pair_preferred_to_hmac_pair(self):
        result = normalize([
            ('raw', [event('request', 'synthetic-jwt'), event('response', 'synthetic-jwt')]),
            ('hmac', [event('request', 'hmac-sha256:fake'), event('response', 'hmac-sha256:fake')]),
        ])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r['_lumen_audit_mode'] == 'raw' for r in result))
        self.assertTrue(all(r['auth']['client_token'] == 'synthetic-jwt' for r in result))

    def test_forwarding_pair_excluded_but_active_operation_retained(self):
        result = normalize([('raw', [
            event('request', request_id='standby'),
            event('response', request_id='standby', error='please forward to the active node'),
            event('request', 'synthetic-jwt'), event('response', 'synthetic-jwt'),
        ])])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r['request']['id'] == 'operation' for r in result))


if __name__ == '__main__':
    unittest.main()
