"""Exercise the UI controller against Verify, Vault, MySQL and xAI; no admin bearer."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from app.security import Identity, Session, load_config
from app.services import Services
from app.telemetry import span, records_for
from app import lab_capture


def verify_capture(identity, session, manager, stages, pair):
    """Check real owner-only inspection without putting capture values in a report."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.trace_inspection import inspection_router
    tids = {stages[action]['traces'][-1] for action in ('prepare', 'access', 'block', 'check')}
    session.traces.extend(tids - set(session.traces))
    records = records_for(tids)
    secrets = [manager._token, *pair.tokens, *[s for c in pair.credentials for s in c.secret.values()]]
    assert all(secret not in json.dumps(records) for secret in secrets if secret), 'secret in telemetry'
    app = FastAPI()
    app.include_router(inspection_router(identity, records_for))
    result = []
    with TestClient(app) as client:
        for record in records:
            if record['name'] not in {'verify.client_credentials', 'verify.token_exchange', 'vault.read',
                                       'vault.write', 'mysql.query', 'xai.auth_probe'}:
                continue
            tid, sid = record['trace_id'], record['span_id']
            stored = lab_capture.STORE.get(tid, sid)
            assert stored and stored['sections'], 'missing call capture'
            assert manager._token not in json.dumps(stored), 'operator bearer in capture'
            url = f'/traces/{tid}/steps/{sid}/sensitive'
            client.cookies.clear()
            assert client.get(url).status_code == 404
            client.cookies.set('lumen_session', session.sid)
            response = client.get(url)
            body = response.json()
            assert response.status_code == 200 and body['sections'] and not body['message']
            assert response.headers['cache-control'] == 'no-store'
            operator = record['attributes'].get('auth.flow') == 'revocation_operator'
            assert bool(body['requests']) is not operator
            if operator: assert body['replay_note']
            result.append({'trace_id': tid, 'span_id': sid, 'name': record['name'],
                           'inspection_http_status': response.status_code, 'section_count': len(body['sections']),
                           'request_templates': len(body['requests']), 'operator_bearer_absent': True,
                           'anonymous_denied': True})
    assert result
    return result


async def main():
    config = load_config()
    identity = Identity(config)
    services = Services(config, identity)
    manager = services.oauth_revocation
    human = json.loads((Path(os.environ['LUMEN_STATE_DIR']) / 'manual/human-writer-task-write.json').read_text())
    claims = identity.validate(human['access_token'], config['task-write']['client_id'])
    session = Session(uuid4().hex, subject=claims['sub'], groups=claims['groups'],
                      access_token=human['access_token'], expires_at=claims['exp'], task_agent='write')
    identity.sessions[session.sid] = session
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'controller': 'app.oauth_revocation_lab.OAuthRevocationLab',
              'ciba_enabled': config.get('contracts', {}).get('enabled'),
              'ciba_auth_mode': config.get('contracts', {}).get('auth_mode'),
              'modes': {}, 'operator_checks': {}}
    try:
        async with manager._client() as client:
            probes = [
                ('other_lease_denied', 'sys/leases/lookup', {'lease_id': 'database/creds/other/not-owned'}),
                ('lease_listing_denied', 'sys/leases/lookup', {}, 'LIST'),
                ('lease_revoke_denied', 'sys/leases/revoke', {'lease_id': 'database/creds/chatbot-readonly/not-owned'}),
                ('policy_management_denied', 'sys/policies/acl/nonexistent-lab-probe', {}, 'GET'),
                ('token_creation_denied', 'auth/token/create', {}),
                ('business_data_denied', 'secrets/data/chatbot/xai-access', {}, 'GET'),
                ('other_issuer_denied', 'auth/token/revoke-oauth', {'issuer': 'https://example.invalid', 'unique_id': uuid4().hex, 'exp': 60}),
            ]
            for name, path, body, *method in probes:
                response = await client.request(method[0] if method else 'POST', '/v1/' + path, json=body)
                report['operator_checks'][name] = response.status_code == 403
        for mode in ('delegated', 'direct'):
            stages = {}
            report['modes'][mode] = stages
            for action in ('prepare', 'access', 'block', 'check'):
                with span('lumen.oauth_revocation.' + action):
                    stages[action] = await getattr(manager, action)(session, mode)
                print(f'{mode}: {action} completed', flush=True)
            pair = manager._pairs[(session.sid, mode)]
            if lab_capture.enabled():
                stages['capture_checks'] = verify_capture(identity, session, manager, stages, pair)
            stages['jwt_seconds_remaining'] = min(c['exp'] for c in pair.claims) - time.time()
            with span('lumen.oauth_revocation.clear'):
                await manager.clear(session, mode)
                for attempt in range(20):
                    states = [await manager._lookup(pair, i, 'cleanup') for i in range(2)]
                    if states == ['missing', 'missing']:
                        break
                    await asyncio.sleep(.5)
                stages['cleanup_original_leases_missing'] = states == ['missing', 'missing']
            assert stages['check']['verified'] and stages['cleanup_original_leases_missing'], mode + ' failed'
        assert all(report['operator_checks'].values()), 'operator policy scope failed'
        report['all_passed'] = True
    finally:
        await manager.close()
        report.setdefault('all_passed', False)
        name = 'oauth-revocation-capture-verification.json' if lab_capture.enabled() else 'oauth-revocation-leases-verification.json'
        output = Path(__file__).resolve().parents[1] / 'docs' / name
        output.write_text(json.dumps(report, indent=2) + '\n')
        print('Sanitized evidence: ' + str(output), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
