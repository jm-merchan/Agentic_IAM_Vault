"""Opt-in live checks after a real OIDC login. Reports contain no credentials."""
import asyncio
import datetime
import json
from pathlib import Path

import httpx
import pymysql


async def verify_session(services, session):
    role = services.role(session)
    tests = []

    def record(name, passed):
        tests.append({'test': name, 'passed': bool(passed)})

    for suffix in ('readonly', 'readwrite'):
        path = 'database/creds/chatbot-' + suffix
        token = await services.exchange(session, path)
        async with httpx.AsyncClient(verify=services.vault_tls, timeout=30) as client:
            response = await client.get(services.config['vault_addr'] + '/v1/' + path,
                                        headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify'})
            allowed = suffix == 'readonly' or role == 'readwrite'
            record('obo_' + suffix + ('_allowed' if allowed else '_denied'),
                   response.status_code == (200 if allowed else 403))
            # Exact RAR cannot be reused to read an unrelated secret.
            denied = await client.get(services.config['vault_addr'] + '/v1/secrets/data/tavily',
                                      headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify'})
            record('obo_' + suffix + '_cannot_read_tavily', denied.status_code == 403)
        if response.status_code == 200:
            credential = response.json()['data']
            def sql_check():
                with pymysql.connect(host='127.0.0.1', port=13306, database='scripting',
                                     user=credential['username'], password=credential['password'],
                                     autocommit=False) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT COUNT(*) FROM energy_plans')
                        record('obo_' + suffix + '_mysql_select', cursor.fetchone()[0] >= 3)
                        try:
                            cursor.execute("INSERT INTO service_requests(subject_id,plan_id,note) VALUES(%s,1,'rolled back OBO verification')", (session.subject,))
                            can_write = True
                            connection.rollback()
                        except pymysql.err.OperationalError as exc:
                            if exc.args[0] != 1142:
                                raise
                            can_write = False
                        record('obo_' + suffix + '_mysql_write_boundary', can_write == (suffix == 'readwrite'))
            await asyncio.to_thread(sql_check)
    report = {'checked_at': datetime.datetime.now(datetime.UTC).isoformat(), 'subject': session.subject,
              'groups': session.groups, 'role': role, 'tests': tests,
              'all_passed': all(t['passed'] for t in tests)}
    is_supervisor = bool(set(session.groups).intersection(services.config['runtime']['groups'].get('sensitive', [])))
    profile = 'supervisor' if is_supervisor and role == 'readonly' else role
    (Path(__file__).parents[1] / 'docs' / ('obo-' + profile + '.json')).write_text(json.dumps(report, indent=2) + '\n')
