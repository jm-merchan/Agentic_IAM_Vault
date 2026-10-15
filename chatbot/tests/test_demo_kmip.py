"""Check first-start KMIP configuration without accessing a real Vault or cluster."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
cmd=pathlib.Path(sys.argv[0]).name; args=sys.argv[1:]
with open(os.environ['KMIP_TEST_EVENTS'], 'a') as log:
    log.write(json.dumps([cmd, args])+'\n')
if cmd == 'curl':
    assert sys.stdin.read() == 'X-Vault-Token: synthetic-root\n'
    pathlib.Path(args[args.index('--output')+1]).write_text(os.environ['KMIP_TEST_BODY'])
    print(os.environ['KMIP_TEST_STATUS'], end='')
elif cmd == 'vault':
    if args[:2] == ['secrets', 'list']:
        print(json.dumps({'kmip/': {'type': 'kmip'}}))
    elif args[:2] != ['write', 'kmip/config']:
        sys.exit('Unexpected Vault mutation')
elif cmd == 'kubectl':
    if 'printenv' in args:
        print('synthetic-mysql')
    elif 'exec' in args:
        print('1')
    elif not any(value in args for value in ['get', 'rollout']):
        sys.exit('Unexpected Kubernetes mutation')
elif cmd == 'lsof':
    print('424242')
elif cmd == 'ps':
    print('kubectl --context workshop -n mysql port-forward svc/mysql-enterprise 13306:3306')
else:
    sys.exit('Unexpected command')
'''


@pytest.mark.parametrize('status,body,success,configure', [
    ('404', {'errors': []}, True, True),
    ('200', {'data': {'listen_addrs': ['0.0.0.0:5696']}}, True, False),
    ('200', {'data': {'listen_addrs': ['127.0.0.1:5696']}}, True, True),
    ('403', {'errors': ['permission denied']}, False, False),
    ('500', {'errors': ['unavailable']}, False, False),
    ('200', {'errors': []}, False, False),
])
def test_kmip_missing_config_is_distinct_from_failed_read(tmp_path, status, body, success, configure):
    root = tmp_path / 'workspace'
    scripts = root / 'scripts/demo'
    scripts.mkdir(parents=True)
    for name in ('common.sh', 'mysql.sh'):
        shutil.copy(ROOT / 'scripts/demo' / name, scripts / name)
    with (scripts / 'common.sh').open('a') as common:
        common.write('\n# Port forwarding is outside the KMIP configuration test.\nstart_forward() { :; }\n')
    state = tmp_path / 'state'
    (state / 'vault').mkdir(parents=True)
    (state / 'vault/config.env').write_text(
        'VAULT_TOKEN=synthetic-root\nVAULT_ADDR=https://vault.invalid\nVAULT_CACERT=synthetic-ca\n'
    )
    (root / '.env').write_text(
        'VERIFY_TENANT=https://verify.invalid\nMYSQL_ROOT_PASSWORD=synthetic-mysql\n'
    )
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name in ('curl', 'vault', 'kubectl', 'lsof', 'ps'):
        command = bindir / name
        command.write_text(MOCK)
        command.chmod(0o700)
    events = tmp_path / 'events.jsonl'
    env = {
        **os.environ,
        'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
        'DEMO_ENV_FILE': str(root / '.env'),
        'LUMEN_STATE_DIR': str(state),
        'KMIP_TEST_EVENTS': str(events),
        'KMIP_TEST_STATUS': status,
        'KMIP_TEST_BODY': json.dumps(body),
    }
    result = subprocess.run(['bash', str(scripts / 'mysql.sh')], env=env,
                            capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    calls = [json.loads(line) for line in events.read_text().splitlines()]
    writes = [args for cmd, args in calls if cmd == 'vault' and args[:1] == ['write']]
    assert bool(writes) == configure
    if not success:
        assert not any(cmd == 'kubectl' for cmd, _ in calls)
    assert 'synthetic-root' not in events.read_text() + result.stdout + result.stderr
