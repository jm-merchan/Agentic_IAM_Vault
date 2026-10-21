"""Real Verify PKCE tokens and real Vault decisions; synthetic protection data."""
import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, UTC
from pathlib import Path

import httpx

from app.security import Identity, Session, AccessDenied, load_config
from app.services import Services
from app.task_agents import actor_credential
from app.telemetry import span, trace_id


async def main():
    role, mode = sys.argv[1:3]
    private = Path(os.environ['MANUAL'])
    name = role if mode == 'legacy' else f'{role}-task-{mode}'
    root_token = os.environ.pop('VAULT_TOKEN')
    config = load_config()
    identity = Identity(config)
    services = Services(config, identity)
    credential = config[actor_credential(config, mode)]
    tokens = json.loads((private / f'human-{name}.json').read_text())
    claims = identity.validate(tokens['access_token'], credential['client_id'])
    identity_claims = identity.validate(tokens['id_token'], credential['client_id'])
    assert claims['sub'] == identity_claims['sub']
    assert identity_claims['nonce'] == (private / f'login-{name}/nonce').read_text()
    assert claims['may_act']['client_id'] == credential['client_id']
    session = Session(name, subject=claims['sub'], groups=claims['groups'],
                      access_token=tokens['access_token'], expires_at=min(claims['exp'], identity_claims['exp']),
                      task_agent=mode)
    leases = []
    vault_get = services.vault_get
    async def tracked_get(path, token, **kwargs):
        result = await vault_get(path, token, **kwargs)
        if result.get('lease_id'):
            leases.append(result['lease_id'])
        return result
    services.vault_get = tracked_get
    evidence = {'role': role, 'task_agent': mode, 'checks': []}
    try:
        with span('verification.task_agents', **{'user.role': role, 'agent.mode': mode}):
            evidence['trace_id'] = trace_id()
            result = await services.permission_probe(session)
            assert '9 de 9 comprobaciones' in result, result
            evidence['checks'].append({'name': 'nine_real_vault_decisions', 'passed': True})
            plans = await services.plans(session)
            assert len(plans) == 3
            evidence['checks'].append({'name': 'mysql_catalogue', 'passed': True})
            # This intentionally bypasses the selector. A subject token issued
            # to one client must not delegate to another task's actor.
            other = 'write' if mode != 'write' else 'read'
            try:
                await services.exchange(replace(session, task_agent=other), 'database/creds/chatbot-readonly')
            except AccessDenied as exc:
                assert 'rechazado la delegación OBO' in str(exc), str(exc)
                evidence['checks'].append({'name': 'verify_rejects_different_actor', 'passed': True})
            else:
                raise AssertionError('Verify accepted an actor not authorized by may_act')
    finally:
        # Revoke only leases issued by this case, including when a check fails.
        async with httpx.AsyncClient(verify=services.vault_tls, timeout=30) as client:
            for lease in leases:
                response = await client.put(config['vault_addr'] + '/v1/sys/leases/revoke',
                                            headers={'X-Vault-Token': root_token, 'X-Vault-Namespace': 'verify'},
                                            json={'lease_id': lease})
                response.raise_for_status()
        evidence['leases_revoked'] = len(leases)
    evidence['checked_at'] = datetime.now(UTC).isoformat()
    output = Path(os.environ['TASK_AGENT_CASES'])
    with output.open('a') as file:
        file.write(json.dumps(evidence) + '\n')
    print(f'{name}: Vault 9/9, MySQL catalogue, wrong actor rejected; {len(leases)} test leases revoked')


asyncio.run(main())
