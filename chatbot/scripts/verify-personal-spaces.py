"""Real OIDC/OBO isolation checks; public report contains no secret values."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from app.personal_spaces import access, configuration
from app.security import load_config, Identity, Session
from app.services import Services
from app.task_agents import actor_credential
from app.telemetry import span


async def main():
    role, mode = sys.argv[1:3]
    config = load_config()
    identity = Identity(config)
    services = Services(config, identity)
    name = role if mode == 'legacy' else f'{role}-task-{mode}'
    private = Path(os.environ['MANUAL'])
    tokens = json.loads((private / f'human-{name}.json').read_text())
    audience = config[actor_credential(config, mode)]['client_id']
    claims = identity.validate(tokens['access_token'], audience)
    id_claims = identity.validate(tokens['id_token'], audience)
    assert claims['sub'] == id_claims['sub']
    assert id_claims['nonce'] == (private / f'login-{name}/nonce').read_text()
    assert claims['may_act']['client_id'] == audience
    session = Session(name, subject=claims['sub'], groups=claims['groups'], access_token=tokens['access_token'],
                      expires_at=min(claims['exp'], id_claims['exp']), task_agent=mode)
    checks = []
    async def check(label, action, expected, **kwargs):
        with span('lumen.personal.' + action, **{'user.id': session.subject, 'agent.mode': mode,
                                               'agent.identity': 'chatbot-' + actor_credential(config, mode)}):
            result = await access(services, session, action, **kwargs)
            passed = result['status'] in expected
            checks.append(dict(test=label, status=result['status'], expected=expected, passed=passed,
                               trace_id=result['trace_id'], path=result['path']))
            print(f'{role}/{mode} {label}: {result["status"]} {"OK" if passed else "FAIL"}')
            return result
    own = await check('own_read', 'read', [200])
    assert own.get('data', {}).get('metadata', {}).get('version', 0) > 0
    await check('own_list', 'list', [200])
    before = await check('existing_test_version', 'read', [200, 404], name='verification')
    version = before.get('data', {}).get('metadata', {}).get('version', 0)
    can_write = mode in ('legacy', 'write')
    written = await check('own_write', 'write', [200] if can_write else [403], name='verification',
                          value={'note': f'Synthetic {role}/{mode}'}, version=version)
    if can_write:
        reread = await check('read_back', 'read', [200], name='verification')
        assert reread['data']['data']['note'] == f'Synthetic {role}/{mode}'
        assert reread['data']['metadata']['version'] == written['data']['version']
        await check('stale_version_rejected', 'write', [400], name='verification',
                    value={'note': 'Must not overwrite'}, version=version)
    for user in configuration(config)['users']:
        if user['subject'] == session.subject:
            continue
        await check('cross_read_' + user['role'], 'read', [403], target=user['subject'])
        await check('cross_list_' + user['role'], 'list', [403], target=user['subject'])
        if can_write:
            await check('cross_write_' + user['role'], 'write', [403], target=user['subject'],
                        name='cross-check', value={'note': 'Must not be written'})
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'role': role, 'mode': mode, 'checks': checks}
    with Path(os.environ['PERSONAL_CASES_FILE']).open('a') as output:
        output.write(json.dumps(report) + '\n')
    assert all(c['passed'] for c in checks), 'Personal space isolation mismatch'


asyncio.run(main())
