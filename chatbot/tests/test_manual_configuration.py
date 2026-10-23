"""Exercise the published manual commands in isolation, without real services."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/manual'


def block(document, number):
    return re.findall(r'^```bash\n(.*?)^```', (DOCS / (document + '.md')).read_text(), re.M | re.S)[number - 1]


def shell(code, env, cwd):
    return subprocess.run(['bash', '-euo', 'pipefail', '-c', code], env=env, cwd=cwd, capture_output=True, text=True)


def executable(path, body):
    path.write_text('#!/usr/bin/env python3\n' + body)
    path.chmod(0o700)


@pytest.fixture
def lab(tmp_path):
    root = tmp_path / 'repo'; root.mkdir()
    scripts = root / 'scripts/manual'; scripts.mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / 'docs/manual').symlink_to(DOCS, target_is_directory=True)
    (root / 'chatbot').mkdir()
    (root / 'chatbot/policies').symlink_to(ROOT / 'chatbot/policies', target_is_directory=True)
    (root / 'scripts/demo').mkdir()
    shutil.copy(ROOT / 'scripts/demo/common.sh', root / 'scripts/demo/common.sh')
    (root / 'verify/scripts').mkdir(parents=True)
    shutil.copy(ROOT / 'verify/scripts/common.sh', root / 'verify/scripts/common.sh')
    for path in (ROOT / 'scripts/manual').glob('*.sh'):
        shutil.copy(path, scripts / path.name)
    shutil.copy(ROOT / 'scripts/manual/guided.py', scripts / 'guided.py')
    state = tmp_path / 'state'; (state / 'vault').mkdir(parents=True)
    (state / 'vault/config.env').write_text('VAULT_ADDR=https://fixture\nVAULT_CACERT=fixture\nVAULT_TOKEN=fixture\n')
    manual = state / 'manual'; manual.mkdir()
    (manual / 'session.sh').write_text('source "$MANUAL_ROOT/.env"\n')
    inputs = {name: 'fixture-' + name.lower() for name in (
        'XAI_MANAGEMENT_API_KEY', 'OPENAI_ADMIN_API_KEY', 'OPENAI_PROJECT_ID',
        'OPENAI_SERVICE_ACCOUNT_ID', 'OPENAI_IDENTITY_PROVIDER_ID', 'NGROK_DOMAIN',
        'ANTHROPIC_FEDERATION_ISSUER_ID', 'ANTHROPIC_FEDERATION_RULE_ID',
        'ANTHROPIC_ORGANIZATION_ID', 'ANTHROPIC_SERVICE_ACCOUNT_ID', 'ANTHROPIC_WORKSPACE_ID')}
    inputs.update(NGROK_DOMAIN='issuer.example', LUMEN_MODEL_PROVIDER='auto',
                  VERIFY_TENANT='https://fixture.verify.ibm.com')
    (root / '.env').write_text(''.join(f'{k}={v}\n' for k, v in inputs.items()))
    bindir = tmp_path / 'bin'; bindir.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LUMEN_', 'MANUAL', 'ANTHROPIC_', 'OPENAI_', 'XAI_', 'SPIFFE_'))}
    env.update(inputs, PATH=str(bindir)+os.pathsep+env['PATH'], LUMEN_STATE_DIR=str(state),
               DEMO_ENV_FILE=str(root / '.env'),
               LUMEN_MANUAL_AWAKE='1', MANUAL_RUN=str(tmp_path / 'report'), MANUAL=str(manual),
               TEST_CATALOG=str(tmp_path / 'catalog.json'), TEST_CALLS=str(tmp_path / 'calls.jsonl'))
    executable(bindir / 'vault', '''import json, os, sys
args=sys.argv[1:]
with open(os.environ['TEST_CALLS'],'a') as f: f.write(json.dumps(args)+'\\n')
if args[:2]==['kv','put']:
    assert args[3:]==['chatbot/model','-']
    with open(os.environ['TEST_CATALOG'],'w') as f: f.write(sys.stdin.read())
elif args[:2]==['kv','get']:
    assert args[-1]=='chatbot/model'
    print(json.dumps({'data':{'data':json.load(open(os.environ['TEST_CATALOG']))}}))
elif args[:2]==['kv','metadata']: pass
elif args[:2]==['policy','write']:
    with open(os.environ['TEST_CATALOG'],'w') as f: f.write(sys.stdin.read())
elif args[0]=='read': print(json.dumps({'data':{'keys':[]}}))
else: raise SystemExit('Unexpected Vault call in isolated test')
''')
    executable(bindir / 'kubectl', '''import json, sys
if '-o' in sys.argv and sys.argv[sys.argv.index('-o')+1]=='json':
 print(json.dumps({'items':[{'metadata':{'name':n,'uid':'new-'+n}} for n in ['vault','mysql','lumen-observability']]}))
''')
    executable(bindir / 'curl', '''import json
print(json.dumps({'status':'ok','issuer':'https://issuer.example/v1/verify/spiffe',
 'models':[{'provider':p} for p in ['openai','xai','anthropic']]}))
''')
    executable(bindir / 'uv', 'pass\n')
    return root, env


def generate_profiles(root, env):
    for document, number in [('06-xai', 10), ('07-openai-spiffe', 13), ('08-claude-spiffe', 7)]:
        result = shell(block(document, number), env, root)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('initial', ['auto', 'xai', 'anthropic'])
def test_manual_catalog_publishes_all_independent_profiles(lab, initial):
    root, env = lab; env['LUMEN_MODEL_PROVIDER'] = initial
    generate_profiles(root, env)
    assert not Path(env['TEST_CALLS']).exists()  # Profile preparation never overwrites Vault.
    result = shell(block('10-aplicacion', 2), env, root)
    assert result.returncode == 0, result.stderr
    config = json.loads(Path(env['TEST_CATALOG']).read_text())
    assert config['provider'] == ('openai' if initial == 'auto' else initial)
    assert set(config['providers']) == {'openai', 'xai', 'anthropic'}
    assert {k: v['model'] for k, v in config['providers'].items()} == {
        'openai': 'gpt-4.1-nano', 'xai': 'grok-4.3', 'anthropic': 'claude-haiku-5-5'}
    assert config['providers']['openai']['service_account_id'] == env['OPENAI_SERVICE_ACCOUNT_ID']
    assert config['providers']['anthropic']['service_account_id'] == env['ANTHROPIC_SERVICE_ACCOUNT_ID']
    assert config['providers']['openai']['spiffe_id'] != config['providers']['anthropic']['spiffe_id']
    assert all('api_key' not in p for p in config['providers'].values())
    calls = [json.loads(line) for line in Path(env['TEST_CALLS']).read_text().splitlines()]
    assert sum(c[:2] == ['kv', 'put'] for c in calls) == 1


@pytest.mark.parametrize('broken', ['missing', 'identity', 'static_key', 'empty_model'])
def test_invalid_catalog_does_not_replace_existing_vault_config(lab, broken):
    root, env = lab; generate_profiles(root, env)
    profile = Path(env['MANUAL']) / 'model-anthropic.json'
    data = json.loads(profile.read_text())
    if broken == 'missing': profile.unlink()
    else:
        if broken == 'identity': data['provider'] = 'openai'
        elif broken == 'static_key': data['api_key'] = 'forbidden-synthetic-key'
        else: data['model'] = ''
        profile.write_text(json.dumps(data))
    catalog = Path(env['TEST_CATALOG']); catalog.write_text('preserve-existing-config')
    result = shell(block('10-aplicacion', 2), env, root)
    assert result.returncode != 0
    assert catalog.read_text() == 'preserve-existing-config'


def test_manual_bootstrap_matches_runtime_policy(lab):
    root, env = lab
    result = shell(block('04-vault-iam', 24), env, root)
    assert result.returncode == 0, result.stderr
    policy = Path(env['TEST_CATALOG']).read_text()
    assert policy.strip() == (ROOT / 'chatbot/policies/bootstrap.hcl').read_text().strip()


def test_manual_groups_command_loads_environment_in_a_new_shell(lab):
    root, env = lab
    for name in ('MANUAL', 'TENANT', 'VAULT_ADDR', 'VAULT_CACERT', 'VAULT_TOKEN',
                 'VAULT_ENV_FILE', 'VAULT_NAMESPACE'):
        env.pop(name, None)
    scripts = root / 'chatbot/scripts'
    scripts.mkdir()
    # Use the actual environment loader; isolate the external mutations.
    (scripts / '05-sync-groups.sh').write_text('''#!/bin/bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
[ "$MANUAL" = "$LUMEN_STATE_DIR/manual" ]
[ "$TENANT" = https://fixture.verify.ibm.com ]
[ "$VAULT_ADDR" = https://fixture ]
[ "$VAULT_CACERT" = fixture ]
[ "$VAULT_NAMESPACE" = verify ]
echo "Entorno completo en shell nuevo"
''')
    code = block('04-vault-iam', 23)
    assert code.strip() == 'bash scripts/manual/paso-a-paso.sh ejecutar grupos'
    result = shell(code, env, root)
    assert result.returncode == 0, result.stderr + result.stdout
    progress = json.loads((Path(env['LUMEN_STATE_DIR']) / 'manual/guided/progress.json').read_text())
    assert progress['steps']['grupos']['status'] == 'ok'
    assert 'Entorno completo en shell nuevo' in Path(progress['steps']['grupos']['log']).read_text()


@pytest.mark.parametrize('suffix,existing_alias,missing_research', [
    ('oidc', True, False),
    ('research', False, False),
    ('oidc', False, True),
])
def test_manual_agent_prerequisites_and_policies(lab, suffix, existing_alias, missing_research):
    root, env = lab
    env.update(suffix=suffix, TENANT='https://verify.example',
               TEST_EXISTING_ALIAS=str(int(existing_alias)), TEST_MISSING_RESEARCH=str(int(missing_research)))
    executable(Path(env['PATH'].split(os.pathsep)[0]) / 'vault', '''import json, os, sys
args = sys.argv[1:]
record = {'args': args}
if args[:2] == ['write', 'agent-registry/register']:
    record['payload'] = json.load(sys.stdin)
with open(os.environ['TEST_CALLS'], 'a') as trace: print(json.dumps(record), file=trace)
suffix = os.environ['suffix']
if args[:2] == ['kv', 'get']:
    if args[-1] == 'chatbot/research' and os.environ['TEST_MISSING_RESEARCH'] == '1':
        raise SystemExit(2)
    print('client-' + args[-1].split('/')[-1])
elif args[0] == 'read':
    path = args[-1]
    if path.startswith('identity/entity/name/'):
        print('entity-' + suffix)
    elif path.startswith('identity/entity/id/'):
        aliases = [{'name': 'chatbot-' + suffix, 'id': 'alias-id'}] if os.environ['TEST_EXISTING_ALIAS'] == '1' else []
        print(json.dumps({'data': {'aliases': aliases}}))
    else:
        print(json.dumps({'display_name': 'chatbot-' + suffix}))
''')
    code = block('04-vault-iam', 9) + ''.join(block('04-vault-iam', n) for n in range(11, 22))
    result = shell(code, env, root)
    calls = [json.loads(line) for line in Path(env['TEST_CALLS']).read_text().splitlines()]
    writes = [call for call in calls if call['args'][0] == 'write']
    if missing_research:
        assert result.returncode != 0
        assert writes == []
        return
    assert result.returncode == 0, result.stderr
    policy = 'chatbot-data-ceiling' if suffix == 'oidc' else 'chatbot-research'
    assert writes[0]['args'] == [
        'write', 'identity/entity/name/chatbot-' + suffix,
        'external_id=client-' + suffix, 'policies=' + policy]
    aliases = [call for call in writes if call['args'][1] == 'identity/entity-alias']
    assert len(aliases) == (0 if existing_alias else 1)
    if aliases:
        assert 'canonical_id=entity-' + suffix in aliases[0]['args']
        assert 'issuer=https://verify.example/oauth2' in aliases[0]['args']
        assert 'external_id=client-' + suffix in aliases[0]['args']
    registration = next(call['payload'] for call in writes if call['args'][1] == 'agent-registry/register')
    assert registration['entity_id'] == 'entity-' + suffix
    assert registration['optional_authorization_details'] == (suffix == 'research')
    assert registration['no_default_ceiling_policy'] is True
    assert registration['ceiling_policies'] == ([policy, 'lumen-block-database-read',
        'lumen-block-database-write', 'lumen-block-decrypt'] if suffix == 'oidc' else [policy])


def test_manual_session_exports_vault_connection_to_child_scripts(lab):
    root, env = lab
    env.pop('VAULT_ENV_FILE', None)
    # A fresh manual install has no legacy /tmp/vault/config.env. Child scripts
    # must receive the path created by chapter 01 through the session export.
    code = block('00-entorno', 2) + '''
bash -euc 'test "$VAULT_ENV_FILE" = "$LUMEN_STATE_DIR/vault/config.env"
source "$VAULT_ENV_FILE"
test "$VAULT_ADDR" = https://fixture'
'''
    result = shell(code, env, root)
    assert result.returncode == 0, result.stderr


def plan_only(root):
    # Extract and parse the real document blocks, but don't execute their side effects.
    with (root / 'scripts/manual/common.sh').open('a') as out:
        out.write('''
step() {
 block "$1" "$2" >/dev/null
 printf '%s %s\\n' "$1" "$2" >> "$MANUAL_RUN/plan"
 printf '{"passed":true}\\n' >> "$MANUAL/steps.jsonl"
 export PUBLISHER_PID=999 SPIFFE_ISSUER=https://issuer.example/v1/verify/spiffe
}
background() {
 block "$1" "$2" >/dev/null
 printf 'background %s %s\\n' "$1" "$2" >> "$MANUAL_RUN/plan"
 printf '{}\\n' >> "$MANUAL/background-blocks.jsonl"
}
wait_port() { :; }
''')


def test_install_plan_includes_all_profiles_before_catalog_and_app(lab):
    root, env = lab; plan_only(root)
    (root / 'scripts/demo/claude-issuer.sh').write_text(
        'printf "claude-issuer-sync\\n" >> "$MANUAL_RUN/plan"\n')
    result = subprocess.run(['bash', 'scripts/manual/install.sh'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plan = (Path(env['MANUAL_RUN']) / 'plan').read_text().splitlines()
    catalog = plan.index('10-aplicacion 2')
    for step in ['06-xai 10', '07-openai-spiffe 13', '08-claude-spiffe 7', '04-vault-iam 24', 'claude-issuer-sync']:
        assert plan.index(step) < catalog
    assert catalog < plan.index('background 10-aplicacion 4')
    report = json.loads((Path(env['MANUAL_RUN']) / 'installation.json').read_text())
    assert report['verification_pending'] and report['all_passed']


def test_verify_plan_checks_claude_denials_and_openai_without_republishing(lab):
    root, env = lab; plan_only(root)
    source = (root / 'scripts/manual/verify.sh').read_text().split('for role in reader writer supervisor;')[0]
    (root / 'scripts/manual/verify-prefix.sh').write_text(source)
    result = subprocess.run(['bash', 'scripts/manual/verify-prefix.sh'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plan = (Path(env['MANUAL_RUN']) / 'plan').read_text().splitlines()
    assert '08-claude-spiffe 14' in plan and '07-openai-spiffe 16' in plan
    assert '08-claude-spiffe 7' not in plan and '10-aplicacion 2' not in plan


def test_rebuild_missing_provider_inputs_stops_before_removal(lab):
    root, env = lab
    (root / '.env').write_text('ANTHROPIC_WORKSPACE_ID=\n')
    (root / 'demo.sh').write_text('touch unexpected-removal\n')
    result = subprocess.run(['bash', 'scripts/manual/rehearse.sh', 'rebuild'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'ANTHROPIC_WORKSPACE_ID' in result.stderr
    assert not (root / 'unexpected-removal').exists()


@pytest.mark.parametrize('verification_succeeds', [False, True])
def test_resume_retains_original_report_and_pending_until_success(lab, verification_succeeds):
    root, env = lab
    scripts = root / 'scripts/manual'
    (scripts / 'install.sh').write_text('mkdir -p "$MANUAL_RUN"\nprintf "[]" > "$MANUAL_RUN/claude-jwks.json"\n')
    result = subprocess.run(['bash', 'scripts/manual/rehearse.sh', 'install'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    pending = Path(env['MANUAL']) / 'pending-verification-run'
    original = env.pop('MANUAL_RUN')
    assert pending.read_text().strip() == original
    (scripts / 'verify.sh').write_text('printf "%s" "$MANUAL_RUN" > "$MANUAL/verified-run"\nexit '+('0' if verification_succeeds else '1')+'\n')
    (scripts / 'finalize.sh').write_text('touch "$MANUAL_RUN/finalized"\n')
    result = subprocess.run(['bash', 'scripts/manual/rehearse.sh', 'verify'], cwd=root, env=env, capture_output=True, text=True)
    assert (Path(env['MANUAL']) / 'verified-run').read_text() == original
    assert (result.returncode == 0) == verification_succeeds
    assert pending.exists() != verification_succeeds
    assert (Path(original) / 'finalized').exists() == verification_succeeds


def test_manual_links_and_bash_blocks_are_valid():
    spec = importlib.util.spec_from_file_location('manual_validate', ROOT / 'scripts/manual/validate.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result = module.validate()
    assert result['all_passed'], result['errors']


def test_static_validation_covers_readme_entrypoint_application_and_notebook(tmp_path):
    spec = importlib.util.spec_from_file_location('workspace_validate', ROOT / 'scripts/manual/validate.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    (tmp_path / 'README.md').write_text('[missing](missing.md)\n')
    (tmp_path / 'demo.sh').write_text('if true; then\n')
    app = tmp_path / 'chatbot/app'; app.mkdir(parents=True)
    (app / 'broken.py').write_text('def broken(:\n')
    (tmp_path / 'example.ipynb').write_text(json.dumps({'nbformat': 4, 'cells': [
        {'cell_type': 'code', 'source': ['%%bash\n', 'echo example\n'],
         'execution_count': 1, 'outputs': [{'output_type': 'stream', 'text': ['historical']}]}]}))
    result = module.validate(tmp_path)
    assert not result['all_passed']
    for filename in ('README.md', 'demo.sh', 'broken.py', 'example.ipynb'):
        assert any(filename in error for error in result['errors'])


@pytest.mark.parametrize('existing_count', [0, 1, 2])
def test_manual_sts_creation_refreshes_inventory_and_does_not_repeat_post(lab, existing_count):
    root, env = lab
    env['TENANT'] = 'https://verify.example'
    manual = Path(env['MANUAL'])
    clients = [{'clientName': 'vault-chatbot-sts', 'clientId': f'existing-{i}'}
               for i in range(existing_count)]
    (manual / 'fake-sts-server.json').write_text(json.dumps({'clients': clients}))
    (manual / 'sts-list.json').write_text('{"clients": []}')  # Stale local inventory.
    executable(Path(env['PATH'].split(os.pathsep)[0]) / 'curl', '''import json, os, sys
from pathlib import Path
path = Path(os.environ['MANUAL']) / 'fake-sts-server.json'
data = json.loads(path.read_text())
args = sys.argv[1:]
if '--request' in args and args[args.index('--request') + 1] == 'POST':
    with open(os.environ['TEST_CALLS'], 'a') as f: print('POST', file=f)
    data['clients'].append({'clientName': 'vault-chatbot-sts', 'clientId': 'created-id'})
    path.write_text(json.dumps(data))
    # The real API can return HTTP 201 with an empty response body.
else:
    print(json.dumps(data))
''')
    for _ in range(2):
        result = shell(block('03-verify', 34), env, root)
        assert result.returncode == 0, result.stderr
    calls = Path(env['TEST_CALLS'])
    assert (calls.read_text().splitlines() if calls.exists() else []) == (
        ['POST'] if existing_count == 0 else [])
    assert len(json.loads((manual / 'fake-sts-server.json').read_text())['clients']) == max(1, existing_count)


def test_manual_sts_failed_inventory_never_creates_client(lab):
    root, env = lab
    env['TENANT'] = 'https://verify.example'
    executable(Path(env['PATH'].split(os.pathsep)[0]) / 'curl', '''import os, sys
if '--request' in sys.argv:
    open(os.environ['TEST_CALLS'], 'w').write('unexpected POST')
else:
    raise SystemExit(22)
''')
    result = shell(block('03-verify', 34), env, root)
    assert result.returncode != 0
    assert not Path(env['TEST_CALLS']).exists()


def fake_scim(env, users=None, groups=None):
    env['TENANT'] = 'https://verify.example'
    manual = Path(env['MANUAL'])
    (manual / 'fake-scim.json').write_text(json.dumps({'Users': users or [], 'Groups': groups or []}))
    executable(Path(env['PATH'].split(os.pathsep)[0]) / 'curl', '''import json, os, sys
from pathlib import Path
from urllib.parse import urlsplit
args = sys.argv[1:]
parts = urlsplit(args[-1]).path.strip('/').split('/')
kind = parts[1]
uid = parts[2] if len(parts) > 2 else None
method = args[args.index('--request') + 1] if '--request' in args else 'GET'
path = Path(os.environ['MANUAL']) / 'fake-scim.json'
data = json.loads(path.read_text())
extension = 'urn:ietf:params:scim:schemas:extension:ibm:2.0:User'
if method == 'GET':
    result = next(item for item in data[kind] if item['id'] == uid) if uid else {'Resources': data[kind]}
else:
    payload = json.loads(Path(args[args.index('--data-binary') + 1][1:]).read_text())
    with open(os.environ['TEST_CALLS'], 'a') as trace: print(json.dumps([method, kind]), file=trace)
    if method == 'POST':
        result = dict(payload, id='created-id')
        if kind == 'Users':
            result[extension] = {'pwdReset': True}
        data[kind].append(result)
    else:
        result = next(item for item in data[kind] if item['id'] == uid)
        if kind == 'Users':
            assert payload['Operations'][0]['path'] == 'password'
            result[extension]['pwdReset'] = False
        else:
            result.setdefault('members', []).extend(payload['Operations'][0]['value'])
    path.write_text(json.dumps(data))
print(json.dumps(result))
''')


@pytest.mark.parametrize('state', ['missing', 'pending', 'ready', 'duplicate'])
def test_manual_user_resumes_without_repeated_creation_or_password_reset(lab, state):
    root, env = lab
    env['ROLE'] = 'reader'
    extension = 'urn:ietf:params:scim:schemas:extension:ibm:2.0:User'
    user = {'id': 'reader-id', 'userName': 'lumen-reader', 'active': True,
            extension: {'pwdReset': state == 'pending'}}
    users = [] if state == 'missing' else [user]
    if state == 'duplicate':
        users.append({**user, 'id': 'other-id'})
    fake_scim(env, users=users)
    manual = Path(env['MANUAL'])
    (manual / 'user-credential.json').write_text(json.dumps({
        'username': 'lumen-reader', 'password': 'synthetic-final-password'}))
    (manual / 'create-user.json').write_text(json.dumps({
        'userName': 'lumen-reader', 'active': True, 'password': 'synthetic-initial-password'}))
    code = ''.join(block('03-verify', n) for n in (44, 45, 47, 48, 49, 50))
    for _ in range(2):
        result = shell(code, env, root)
        if state == 'duplicate':
            assert result.returncode != 0
        else:
            assert result.returncode == 0, result.stderr
            assert json.loads((manual / 'user-check.json').read_text())[extension]['pwdReset'] is False
    calls = Path(env['TEST_CALLS'])
    mutations = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    expected = [['POST', 'Users'], ['PATCH', 'Users']] if state == 'missing' else (
        [['PATCH', 'Users']] if state == 'pending' else [])
    assert mutations == expected


@pytest.mark.parametrize('state', ['missing', 'missing_member', 'member', 'duplicate'])
def test_manual_group_reuses_group_and_adds_membership_only_once(lab, state):
    root, env = lab
    env.update(ROLE='reader', USER_ID='reader-id', GROUP='chatbot-readers')
    member = {'value': 'reader-id', 'type': 'user'}
    group = {'id': 'group-id', 'displayName': 'chatbot-readers',
             'members': [member] if state == 'member' else []}
    groups = [] if state == 'missing' else [group]
    if state == 'duplicate':
        groups.append({**group, 'id': 'other-group-id'})
    fake_scim(env, groups=groups)
    manual = Path(env['MANUAL'])
    (manual / 'create-group.json').write_text(json.dumps({
        'displayName': 'chatbot-readers', 'members': [member]}))
    for _ in range(2):
        result = shell(block('03-verify', 53), env, root)
        if state == 'duplicate':
            assert result.returncode != 0
        else:
            assert result.returncode == 0, result.stderr
            assert json.loads((manual / 'group-reader.json').read_text())['members'] == [member]
    calls = Path(env['TEST_CALLS'])
    mutations = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    expected = [['POST', 'Groups']] if state == 'missing' else (
        [['PATCH', 'Groups']] if state == 'missing_member' else [])
    assert mutations == expected


@pytest.mark.parametrize('response', [
    {'userName': 'lumen-reader', 'id': 'reader-id'},
    {'userName': 'lumen-supervisor', 'id': 'supervisor-id'},
    {'userName': 'lumen-reader'},
    {'userName': 'lumen-reader', 'id': ''},
])
def test_manual_user_id_must_match_current_credential(lab, response):
    root, env = lab
    manual = Path(env['MANUAL'])
    (manual / 'user-credential.json').write_text(json.dumps({
        'username': 'lumen-reader', 'password': 'synthetic-password',
    }))
    (manual / 'user.json').write_text(json.dumps(response))
    result = shell(block('03-verify', 45) + '\nprintf "%s" "$USER_ID"', env, root)
    if response == {'userName': 'lumen-reader', 'id': 'reader-id'}:
        assert result.returncode == 0, result.stderr
        assert result.stdout == 'reader-id'
    else:
        assert result.returncode != 0
        assert result.stdout == ''


@pytest.mark.parametrize('credential', [
    {'username': 'lumen-reader', 'password': 'synthetic-password'},
    {'username': 'lumen-supervisor', 'password': 'synthetic-password'},
    {'username': 'lumen-reader'},
    '',
    None,
])
def test_manual_user_write_never_sends_missing_or_wrong_credential(lab, credential):
    root, env = lab
    env.update(ROLE='reader', USER_ID='reader-id')
    path = Path(env['MANUAL']) / 'user-credential.json'
    if credential is not None:
        path.write_text(json.dumps(credential) if isinstance(credential, dict) else credential)
    executable(Path(env['PATH'].split(os.pathsep)[0]) / 'vault', '''import json, os, sys
with open(os.environ['TEST_CALLS'], 'w') as f:
    json.dump({'args': sys.argv[1:], 'data': sys.stdin.read()}, f)
''')
    result = shell(block('03-verify', 46), env, root)
    calls = Path(env['TEST_CALLS'])
    if credential == {'username': 'lumen-reader', 'password': 'synthetic-password'}:
        assert result.returncode == 0, result.stderr
        call = json.loads(calls.read_text())
        assert call['args'] == ['kv', 'put', '-mount=secrets', 'chatbot/users/reader', '-']
        assert json.loads(call['data']) == {**credential, 'user_id': 'reader-id'}
    else:
        assert result.returncode != 0
        assert not calls.exists()


def test_manual_audit_filter_covers_both_federated_identities(lab):
    root, env = lab
    result = shell(block('09-observabilidad', 3)+'\nprintf "%s" "$SPIFFE_FILTER"', env, root)
    assert result.returncode == 0, result.stderr
    assert 'spiffe/role/lumen-openai/mintjwt' in result.stdout
    assert 'spiffe/role/lumen-anthropic/mintjwt' in result.stdout
    runtime = (ROOT / 'chatbot/scripts/enable-audit.sh').read_text()
    assert "SPIFFE_FILTER='"+result.stdout+"'" in runtime


@pytest.mark.parametrize('mode,successful', [('existing', True), ('install', True), ('rebuild', True), ('reused_namespace', False)])
def test_finalize_only_reports_rebuild_with_distinct_namespaces_and_users(lab, mode, successful):
    root, env = lab; report = Path(env['MANUAL_RUN']); report.mkdir()
    (report / 'workflows.json').write_text(json.dumps({'all_passed': True, 'checks': []}))
    (report / 'final-state.json').write_text(json.dumps({'all_blocks_inactive': True}))
    (report / 'verification-state.json').write_text(json.dumps({'verification_pending': True}))
    if mode != 'existing':
        (report / 'installation.json').write_text(json.dumps({'all_passed': True}))
    if mode in ('rebuild', 'reused_namespace'):
        prefix = 'old-' if mode == 'rebuild' else 'new-'
        (report / 'before.json').write_text(json.dumps([{'name': n, 'uid': prefix+n} for n in ['vault','mysql','lumen-observability']]))
        (report / 'remove.json').write_text(json.dumps({'verify_resources': [{'kind':'user','id':'old-user'}]}))
        (report / 'users.json').write_text(json.dumps({'users':[{'user_id':str(i)} for i in range(3)]}))
    result = subprocess.run(['bash', 'scripts/manual/finalize.sh'], cwd=root, env=env, capture_output=True, text=True)
    assert (result.returncode == 0) == successful, result.stderr
    outcome = json.loads((report / 'result.json').read_text())
    assert outcome['all_passed'] == successful
    if mode in ('existing','install'): assert 'rebuilt_namespaces' not in outcome
    else: assert outcome['rebuilt_namespaces'] == successful
    assert json.loads((report / 'verification-state.json').read_text())['verification_pending'] != successful
