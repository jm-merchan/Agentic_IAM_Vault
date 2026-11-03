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
from app.telemetry import span


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
        output = Path(__file__).resolve().parents[1] / 'docs/oauth-revocation-leases-verification.json'
        output.write_text(json.dumps(report, indent=2) + '\n')
        print('Sanitized evidence: ' + str(output), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
