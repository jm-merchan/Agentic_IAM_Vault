"""Real OIDC/PKCE + Verify OBO + Vault comparisons; report contains no tokens."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from app.rar_lab import run_comparison, scenarios
from app.security import load_config, Identity, Session
from app.services import Services
from app.task_agents import actor_credential
from app.telemetry import span, trace_id


async def main():
    role, mode = sys.argv[1:3]
    config = load_config()
    identity = Identity(config)
    services = Services(config, identity)
    name = role if mode == 'legacy' else f'{role}-task-{mode}'
    private = Path(os.environ['MANUAL'])
    tokens = json.loads((private / f'human-{name}.json').read_text())
    claims = identity.validate(tokens['access_token'], config[actor_credential(config, mode)]['client_id'])
    identity_claims = identity.validate(tokens['id_token'], config[actor_credential(config, mode)]['client_id'])
    assert claims['sub'] == identity_claims['sub']
    assert identity_claims['nonce'] == (private / f'login-{name}/nonce').read_text()
    assert claims['may_act']['client_id'] == config[actor_credential(config, mode)]['client_id']
    session = Session(name, subject=claims['sub'], groups=claims['groups'], access_token=tokens['access_token'],
                      expires_at=min(claims['exp'], identity_claims['exp']), task_agent=mode)
    checks = []
    keys = ['allowed'] if mode == 'read' or mode == 'legacy' else ['decrypt'] if role == 'supervisor' else [k for k in scenarios(config) if k != 'decrypt']
    for key in keys:
        with span('lumen.rar.compare', **{'user.role': role, 'agent.mode': mode,
                                        'agent.identity': 'chatbot-' + actor_credential(config, mode)}):
            rows = await run_comparison(services, session, key, 'all')
            for row in rows:
                expected = 'baseline_denied' if mode == 'read' else 'allowed' if row['expected'] else 'rar_denied'
                passed = row['interpretation'] == expected
                checks.append(dict(scenario=key, case=row['case'], baseline=row['phases']['baseline']['status'],
                                   restricted=row['phases']['restricted']['status'], expected=expected,
                                   interpretation=row['interpretation'], passed=passed, trace_id=trace_id(),
                                   request_ids=[v.get('request_id','') for v in row['phases'].values()]))
                print(f'{role}/{mode} {key}/{row["case"]}: {checks[-1]["baseline"]}/{checks[-1]["restricted"]} {"OK" if passed else "FAIL"}')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'role': role, 'mode': mode, 'checks': checks}
    with Path(os.environ['RAR_CASES_FILE']).open('a') as output:
        output.write(json.dumps(report) + '\n')
    assert all(c['passed'] for c in checks), 'RAR comparison mismatch; inspect private traces'


asyncio.run(main())
