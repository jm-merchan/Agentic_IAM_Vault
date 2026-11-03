"""Real revoke-oauth lab: delegated SQL and direct non-secret KV access."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import ssl
import time
from uuid import uuid4

import httpx
import pymysql
from opentelemetry.trace import Status, StatusCode

from app.rar import authorization_details
from app.security import Identity, ISSUER, Session, load_config
from app.services import Services
from app.telemetry import headers, span, trace_id

ROOT = Path(__file__).resolve().parents[2]
PATHS = {'delegated': 'database/creds/chatbot-readonly',
         'direct': 'secrets/data/chatbot/xai-access'}


def revocation_payload(claims, *, now=None, leeway=15):
    """The API's exp is a duration, unlike the JWT's epoch exp timestamp."""
    now = time.time() if now is None else now
    if (not isinstance(claims.get('iss'), str) or not claims['iss']
            or not isinstance(claims.get('jti'), str) or not claims['jti']
            or type(claims.get('exp')) not in (int, float)
            or not math.isfinite(claims['exp']) or claims['exp'] <= now):
        raise ValueError('A live JWT with issuer, jti and expiry is required.')
    return {'issuer': claims['iss'], 'unique_id': claims['jti'],
            'exp': math.ceil(claims['exp'] - now) + leeway}


def operator_policy(payload):
    # JSON literals are also HCL literals; never interpolate unquoted claim text.
    if any('*' in payload[key] for key in ('issuer', 'unique_id')):
        raise ValueError('The operator scope must use literal issuer and unique_id values.')
    return ('path "auth/token/revoke-oauth" {\n'
            '  capabilities = ["update"]\n'
            '  required_parameters = ["issuer", "unique_id", "exp"]\n'
            '  allowed_parameters = {\n'
            f'    "issuer" = [{json.dumps(payload["issuer"])}]\n'
            f'    "unique_id" = [{json.dumps(payload["unique_id"])}]\n'
            '    "exp" = []\n'
            '  }\n}\n')


def assert_live_denial(status, claims, observed_at):
    if status != 403 or claims['exp'] - observed_at <= 30:
        raise AssertionError('Expected HTTP 403 with more than 30 seconds left before JWT expiry.')


def assert_pair(a, b, *, mode, subject, actor, rar):
    assert a['jti'] != b['jti'], 'Verify must issue distinct jti values for A and B.'
    for claims in (a, b):
        assert claims['iss'] == ISSUER and claims['sub'] == subject
        assert claims.get('authorization_details') == rar
        if mode == 'delegated':
            assert claims.get('actor-token', {}).get('sub') == actor
        else:
            assert not claims.get('actor-token'), 'The direct JWT must not carry a delegated actor.'


class Lab:
    def __init__(self, config, admin_token, pause=False):
        self.config, self.admin_token, self.pause = config, admin_token, pause
        self.identity = Identity(config)
        self.services = Services(config, self.identity)
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
        self.private = Path(os.environ['LUMEN_STATE_DIR']) / 'oauth-revocation' / self.run_id
        self.private.mkdir(mode=0o700, parents=True)
        self.http = httpx.AsyncClient(base_url=config['vault_addr'], timeout=30,
            verify=ssl.create_default_context(cafile=config['vault_ca']))

    async def request(self, method, path, token, payload=None, *, phase='', mode='', actor=''):
        attrs = {'vault.path': path, 'vault.namespace': 'verify', 'http.request.method': method,
                 'lab.mode': mode, 'revocation.lab.phase': phase, 'agent.identity': actor,
                 'auth.flow': 'revocation_operator' if 'revoke-oauth' in path else mode}
        with span('vault.read' if method == 'GET' else 'vault.write', **attrs) as current:
            result = await self.http.request(method, '/v1/' + path, json=payload,
                headers={'X-Vault-Token': token, 'X-Vault-Namespace': 'verify', **headers()})
            current.set_attribute('http.response.status_code', result.status_code)
            try:
                body = result.json()
            except ValueError:
                body = {}
            current.set_attribute('vault.request_id', body.get('request_id', ''))
            return result.status_code, body

    async def admin(self, method, path, payload=None):
        # Bootstrap/setup responses may contain credentials. Never trace their bodies.
        r = await self.http.request(method, '/v1/' + path, json=payload,
            headers={'X-Vault-Token': self.admin_token, 'X-Vault-Namespace': 'verify'})
        if r.status_code not in (200, 204):
            raise RuntimeError(f'Lab setup/cleanup failed: {method} {path}, HTTP {r.status_code}')
        return r.json() if r.content else {}

    async def direct_token(self, rar):
        credential = self.config['xai']
        with span('verify.client_credentials', **{'agent.identity': 'chatbot-xai', 'lab.mode': 'direct'}) as current:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(ISSUER + '/token',
                    auth=(credential['client_id'], credential['client_secret']),
                    data={'grant_type': 'client_credentials', 'scope': 'openid profile email',
                          'authorization_details': json.dumps(rar)})
            current.set_attribute('http.response.status_code', r.status_code)
            if r.status_code != 200:
                raise RuntimeError(f'Client Credentials failed: HTTP {r.status_code}')
            return r.json()['access_token']

    async def sql(self, credential, *, mode, phase):
        def connect():
            with span('mysql.query', **{'db.system': 'mysql', 'db.role': 'readonly',
                      'db.statement': 'SELECT 1', 'lab.mode': mode, 'revocation.lab.phase': phase}) as current:
                try:
                    with pymysql.connect(host='127.0.0.1', port=13306, connect_timeout=5,
                            user=credential['username'], password=credential['password']) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT 1')
                            assert cursor.fetchone()[0] == 1
                    return True
                except pymysql.MySQLError as exc:
                    if exc.args[0] not in (1045, 3118):
                        raise RuntimeError('SQL check failed for a reason other than revoked authentication.') from None
                    current.set_attribute('db.error.code', exc.args[0])
                    current.set_status(Status(StatusCode.ERROR))
                    return False
        return await asyncio.to_thread(connect)

    async def scenario(self, mode, session=None):
        checks, claims, operator, policy_name, revoked = [], [], '', '', False
        path, rar = PATHS[mode], authorization_details(PATHS[mode], ['read'])
        actor_name = 'chatbot-task-write' if mode == 'delegated' else 'chatbot-xai'
        folder = self.private / mode
        folder.mkdir(mode=0o700)
        def check(name, condition):
            if not condition:
                raise AssertionError(name)
            checks.append(name)
            print(f'{mode}: {name} OK', flush=True)
        try:
            if mode == 'delegated':
                a = await self.services.exchange(session, path, ['read'])
                b = await self.services.exchange(session, path, ['read'])
                subject, actor = session.subject, self.config['task-write']['client_id']
            else:
                a, b = await self.direct_token(rar), await self.direct_token(rar)
                subject, actor = self.config['xai']['client_id'], None
            claims = [await asyncio.to_thread(self.identity.validate, token, None) for token in (a, b)]
            ca, cb = claims
            assert_pair(ca, cb, mode=mode, subject=subject, actor=actor, rar=rar)
            check('same identity and RAR; distinct JWT identifiers', True)
            payload = revocation_payload(ca)
            policy_name = 'lumen-oauth-revocation-lab-' + uuid4().hex
            policy = operator_policy(payload)
            await self.admin('PUT', 'sys/policies/acl/' + policy_name, {'policy': policy})
            created = await self.admin('POST', 'auth/token/create', {
                'policies': [policy_name], 'no_default_policy': True, 'ttl': '5m',
                'explicit_max_ttl': '5m', 'display_name': 'lumen-revoke-oauth-lab-operator'})
            operator = created['auth']['client_token']
            for name, value in {'revoke-a.json': json.dumps(payload, indent=2) + '\n',
                                'operator-policy.hcl': policy,
                                'claims-a.json': json.dumps({k: ca[k] for k in ('iss', 'jti', 'exp', 'sub')}, indent=2) + '\n'}.items():
                (folder / name).write_text(value);(folder / name).chmod(0o600)
            if self.pause:
                for name, token in [('token-a', a), ('token-b', b), ('operator', operator)]:
                    file = folder / (name + '.headers')
                    file.write_text('X-Vault-Token: ' + token + '\nX-Vault-Namespace: verify\n')
                    file.chmod(0o600)
            status, first = await self.request('GET', path, a, mode=mode, phase='before-a', actor=actor_name)
            issued_at = time.time()
            check('token A allowed before revocation (HTTP 200)', status == 200)
            if mode == 'delegated':
                check('leased SQL credential accepts a new connection', await self.sql(first['data'], mode=mode, phase='sql-before'))
            # The restricted operator must be unable to revoke the control JWT.
            wrong = {**payload, 'unique_id': cb['jti']}
            status, _ = await self.request('POST', 'auth/token/revoke-oauth', operator, wrong,
                                           mode=mode, phase='operator-negative')
            check('operator cannot revoke token B (HTTP 403)', status == 403)
            if self.pause:
                print(f'Private files: {folder}\nRun the manual API call now or press Enter to let the runner send it. Continue within 60 seconds.', flush=True)
                await asyncio.to_thread(input, 'Enter to revoke token A: ')
            check('JWT A still has more than 30 seconds before expiry', ca['exp'] - time.time() > 30)
            if mode == 'delegated':
                check('SQL lease has not expired before revocation',
                      first['lease_duration'] - (time.time() - issued_at) > 15)
            status, _ = await self.request('POST', 'auth/token/revoke-oauth', operator, payload,
                                           mode=mode, phase='revoke-a')
            check('revoke-oauth accepted issuer and unique_id, without the JWT', status in (200, 204))
            revoked = True
            status, _ = await self.request('GET', path, a, mode=mode, phase='after-a', actor=actor_name)
            observed_at = time.time()
            assert_live_denial(status, ca, observed_at)
            check('same token A denied before expiry (HTTP 403)', True)
            await asyncio.to_thread(self.identity.validate, a, None)
            check('revoked JWT still has a valid signature and unexpired claims', True)
            if mode == 'delegated':
                for attempt in range(20):
                    if not await self.sql(first['data'], mode=mode, phase='sql-after'):
                        break
                    await asyncio.sleep(.25)
                else:
                    raise AssertionError('SQL user still accepts new connections after JWT revocation.')
                check('SQL rejection occurred before the original lease expiry',
                      first['lease_duration'] - (time.time() - issued_at) > 0)
            status, control = await self.request('GET', path, b, mode=mode, phase='control-b', actor=actor_name)
            check('unrevoked token B still allowed (HTTP 200)', status == 200)
            if mode == 'delegated':
                check('token B can still obtain a working SQL credential', await self.sql(control['data'], mode=mode, phase='sql-control'))
            return {'mode': mode, 'passed': True, 'path': path, 'agent': actor_name,
                    'subject': subject, 'actor': actor, 'issuer': ca['iss'],
                    'unique_id_a': ca['jti'], 'unique_id_b': cb['jti'],
                    'jwt_exp': ca['exp'], 'revoke_payload': payload,
                    'seconds_until_exp_at_denial': round(ca['exp'] - observed_at, 3),
                    'checks': checks, 'trace_id': trace_id()}
        finally:
            failures = []
            for index, value in enumerate(claims):
                if index == 0 and revoked:
                    continue
                if value.get('exp', 0) > time.time():
                    try:
                        await self.admin('POST', 'auth/token/revoke-oauth', revocation_payload(value))
                    except Exception:
                        failures.append('temporary OAuth JWT')
            if operator:
                try:
                    await self.admin('POST', 'auth/token/revoke', {'token': operator})
                except Exception:
                    failures.append('temporary operator token')
            if policy_name:
                try:
                    await self.admin('DELETE', 'sys/policies/acl/' + policy_name)
                    r = await self.http.get('/v1/sys/policies/acl/' + policy_name,
                        headers={'X-Vault-Token': self.admin_token, 'X-Vault-Namespace': 'verify'})
                    if r.status_code != 404:
                        failures.append('temporary operator policy')
                except Exception:
                    failures.append('temporary operator policy')
            for file in folder.glob('*.headers'):
                file.unlink()
            if failures:
                raise RuntimeError('Lab cleanup failed for: ' + ', '.join(failures))


async def main(mode, pause):
    admin = os.environ.pop('VAULT_TOKEN')
    config = load_config()
    lab = Lab(config, admin, pause)
    session = None
    try:
        profile = (await lab.admin('GET', 'sys/config/oauth-resource-server/verify'))['data']
        assert profile.get('unique_id_claim', 'jti') == 'jti' and profile['issuer_id'] == ISSUER
        if mode != 'direct':
            tokens = json.loads((Path(os.environ['LUMEN_STATE_DIR']) / 'manual/human-writer-task-write.json').read_text())
            human = lab.identity.validate(tokens['access_token'], config['task-write']['client_id'])
            session = Session('oauth-revocation-lab', subject=human['sub'], groups=human['groups'],
                access_token=tokens['access_token'], expires_at=human['exp'], task_agent='write')
        scenarios = []
        for selected in ('delegated', 'direct') if mode == 'both' else (mode,):
            with span('lumen.oauth_revocation_lab', **{'lab.mode': selected}):
                scenarios.append(await lab.scenario(selected, session))
        report = {'checked_at': datetime.now(timezone.utc).isoformat(),
            'flow': 'oauth-revocation-api', 'run_id': lab.run_id, 'passed': True,
            'endpoint': 'auth/token/revoke-oauth', 'namespace': 'verify',
            'cleanup_passed': True, 'scenarios': scenarios,
            'scope': 'Fresh lab JWTs only; no changes to business ACLs, agents or clients; no model calls.'}
        report_path = ROOT / 'chatbot/docs/oauth-revocation-verification.json'
        # Preserve the combined evidence if an operator later runs only one branch.
        if mode != 'both':
            report_path = report_path.with_name('oauth-revocation-' + mode + '-verification.json')
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(f'Passed {sum(len(s["checks"]) for s in scenarios)} live checks. Report: {report_path.relative_to(ROOT)}', flush=True)
    finally:
        await lab.http.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='both', choices=('delegated', 'direct', 'both'))
    parser.add_argument('--pause', action='store_true', help='Pause before each revocation; publish temporary private curl headers.')
    args = parser.parse_args()
    asyncio.run(main(args.mode, args.pause))
