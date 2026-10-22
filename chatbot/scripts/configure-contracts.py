"""Provision a dedicated Verify validator and confidential CIBA client."""
import argparse
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess

import httpx

ROOT = Path(__file__).resolve().parents[2]
TENANT = os.environ['VERIFY_TENANT'].rstrip('/')
APP_NAME = 'vault-chatbot-contract'
USERNAME = 'lumen-validator'
GROUP = 'chatbot-validators'


def request(client, method, path, body=None, *, missing=False, **kwargs):
    result = client.request(method, path, json=body, **kwargs)
    if missing and result.status_code == 404:
        return None
    if result.status_code not in (200, 201, 204):
        raise RuntimeError(f'HTTP {result.status_code}: {method} {path}')
    return result.json() if result.content else {}


def configure(vault, verify, validator=None, enable=False):
    def v(method, path, body=None, **kwargs):
        value = request(vault, method, '/v1/' + path, body, **kwargs)
        return value.get('data', {}) if value is not None else None

    def kv(name, value=None, missing=False):
        if value is not None:
            return v('POST', 'secrets/data/chatbot/' + name, {'data': value})
        value = v('GET', 'secrets/data/chatbot/' + name, missing=missing)
        return value['data'] if value else None

    admin = v('GET', 'secrets/data/verify-admin')['data']
    token = verify.post('/oauth2/token', auth=(admin['client_id'], admin['client_secret']),
                        data={'grant_type': 'client_credentials'})
    if token.status_code != 200:
        raise RuntimeError('Verify admin authentication failed.')
    verify.headers['Authorization'] = 'Bearer ' + token.json()['access_token']

    def api(method, path, body=None, **kwargs):
        return request(verify, method, path, body, **kwargs)

    def one(items, label):
        if len(items) > 1:
            raise RuntimeError('Duplicate ' + label)
        return items[0] if items else None

    previous = kv('contracts', missing=True) or {}
    state_path = Path(os.environ.get('LUMEN_STATE_DIR', str(Path.home() / '.local/state/lumen-vault-demo'))) / 'contracts/validator.json'
    saved = json.loads(state_path.read_text()) if state_path.exists() else {}
    prior_validator = kv('pdf-approval', missing=True) or {}
    username = validator or previous.get('validator_username') or saved.get('username') or prior_validator.get('validator_username') or USERNAME
    if username != USERNAME:
        user = one(api('GET', '/v2.0/Users', params={'filter': f'userName eq "{username}"'})['Resources'], username)
        if user is None:
            # Federated IBMid names include an identity-source suffix. Resolve the
            # exact email, require uniqueness, then retain the real SCIM username.
            matches, offset = [], 1
            while True:
                page = api('GET', '/v2.0/Users', params={'attributes': 'id,userName,active,emails',
                           'startIndex': offset, 'count': 100})
                matches += [u for u in page['Resources'] if any(
                    e.get('value', '').casefold() == username.casefold() for e in u.get('emails', []))]
                offset += len(page['Resources'])
                if not page['Resources'] or offset > page['totalResults']:
                    break
            user = one(matches, username)
        if user is None or not user.get('active'):
            raise RuntimeError('The selected existing validator is absent or disabled.')
        username = user['userName']
        uid = user['id']
    else:
        credential = kv('users/validator', missing=True)
        user = one(api('GET', '/v2.0/Users', params={'filter': f'userName eq "{USERNAME}"'})['Resources'], USERNAME)
        if credential is None:
            if user is not None:
                raise RuntimeError('Existing validator without managed credentials; refusing to reset it.')
            credential = {'username': USERNAME, 'password': 'Lu!9' + secrets.token_hex(20)}
            # Save first so an interrupted installation can resume without losing credentials.
            kv('users/validator', credential)
        if credential.get('username') != USERNAME:
            raise RuntimeError('Unexpected validator username.')
        if user is None:
            user = api('POST', '/v2.0/Users', {
                'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User',
                            'urn:ietf:params:scim:schemas:extension:ibm:2.0:User',
                            'urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification'],
                'userName': USERNAME, 'password': 'Lu!9' + secrets.token_hex(20), 'active': True,
                'name': {'givenName': 'Lumen', 'familyName': 'Validator', 'formatted': 'Lumen Validator'},
                'displayName': 'Lumen Validator',
                'emails': [{'type': 'work', 'value': USERNAME + '@example.invalid', 'primary': True}],
                'urn:ietf:params:scim:schemas:extension:ibm:2.0:User': {
                    'userCategory': 'regular', 'realm': 'cloudIdentityRealm', 'pwdReset': True},
                'urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification': {'notifyType': 'NONE'},
            }, headers={'Content-Type': 'application/scim+json'})
        uid = user['id']
        if not user.get('active'):
            raise RuntimeError('Validator is disabled; refusing to reactivate automatically.')
        if user.get('urn:ietf:params:scim:schemas:extension:ibm:2.0:User', {}).get('pwdReset'):
            api('PATCH', '/v2.0/Users/' + uid, {
                'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
                'Operations': [{'op': 'replace', 'path': 'password', 'value': credential['password']},
                               {'op': 'add', 'path': 'urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification:notifyType', 'value': 'NONE'}],
            }, headers={'Content-Type': 'application/scim+json', 'usershouldnotneedtoresetpassword': 'true'})
        credential['user_id'] = uid
        kv('users/validator', credential)
    group = one(api('GET', '/v2.0/Groups', params={'filter': f'displayName eq "{GROUP}"'})['Resources'], GROUP)
    if group is None:
        group = api('POST', '/v2.0/Groups', {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group', 'urn:ietf:params:scim:schemas:extension:ibm:2.0:Group'],
            'displayName': GROUP, 'externalId': 'lumen-demo:contract-validators',
            'members': [{'value': uid, 'type': 'user'}],
            'urn:ietf:params:scim:schemas:extension:ibm:2.0:Group': {'groupType': 'standard'},
        }, headers={'Content-Type': 'application/scim+json'})
    else:
        group = api('GET', '/v2.0/Groups/' + group['id'])
        if group.get('externalId') != 'lumen-demo:contract-validators':
            managed_ids = {previous.get('validator_group'), prior_validator.get('validator_group')}
            if group.get('externalId') or group['id'] not in managed_ids:
                raise RuntimeError('Validator group is not managed by this demo; refusing to adopt it.')
            api('PATCH', '/v2.0/Groups/' + group['id'], {
                'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
                'Operations': [{'op': 'add', 'path': 'externalId', 'value': 'lumen-demo:contract-validators'}],
            }, headers={'Content-Type': 'application/scim+json'})
        if uid not in [member['value'] for member in group.get('members', [])]:
            api('PATCH', '/v2.0/Groups/' + group['id'], {
                'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
                'Operations': [{'op': 'add', 'path': 'members', 'value': [{'value': uid, 'type': 'user'}]}],
            }, headers={'Content-Type': 'application/scim+json'})

    apps = api('GET', '/v1.0/applications')['_embedded']['applications']
    # Retire only the earlier managed PDF experiment, without changing its users.
    for old in (a for a in apps if a['name'] == 'vault-chatbot-pdf-approval'):
        old_path = '/v1.0/applications/' + old['_links']['self']['href'].split('/')[-1]
        old_app = api('GET', old_path)
        if old_app['providers']['oidc']['properties']['clientId'] == prior_validator.get('client_id'):
            old_app.update(applicationState=False, signonState=False)
            api('PUT', old_path, old_app)
    application = one([a for a in apps if a['name'] == APP_NAME], APP_NAME)
    if application is None:
        template = json.loads((ROOT / 'verify/config/oidc-template.json').read_text())
        body = {key: template[key] for key in ('templateId', 'applicationState', 'signonState', 'providers', 'identitySources', 'provisioningMode')}
        body.update(name=APP_NAME, description='Lumen contract confirmation through CIBA', visibleOnLaunchpad=False, approvalRequired=False)
        props = body['providers']['oidc']['properties']
        props.pop('clientId', None)
        props.pop('clientSecret', None)
        props['grantTypes'] = {k: 'true' if k == 'ciba' else 'false' for k in props['grantTypes']}
        body['providers']['oidc']['token']['attributeMappings'] = []
        api('POST', '/v1.0/applications', body)
        apps = api('GET', '/v1.0/applications')['_embedded']['applications']
        application = one([a for a in apps if a['name'] == APP_NAME], APP_NAME)
    aid = application['_links']['self']['href'].split('/')[-1]
    application = api('GET', '/v1.0/applications/' + aid)
    oidc = application['providers']['oidc']
    props = oidc['properties']
    cid = props['clientId']
    props['grantTypes'] = {k: 'true' if k == 'ciba' else 'false' for k in props['grantTypes']}
    props['generateRefreshToken'] = 'false'
    props['accessTokenExpiry'] = 600
    props['additionalConfig'].update(restrictAuthDetailTypes=True, ignoreUnknownAuthDetailTypes=False, authDetailTypes=[])
    oidc['consentAction'] = 'always_prompt'
    oidc['token']['accessTokenType'] = 'jwt'
    oidc['token']['attributeMappings'] = [{'targetName': 'groups', 'sourceId': '4'}]
    api('PUT', '/v1.0/applications/' + aid, application)
    updated = api('GET', '/v1.0/applications/' + aid)['providers']['oidc']
    grants = updated['properties']['grantTypes']
    if grants.get('ciba') != 'true' or any(value != 'false' for key, value in grants.items() if key != 'ciba'):
        raise RuntimeError('Verify did not restrict this client to CIBA only.')
    api('POST', '/v1.0/owner/applications/' + aid + '/entitlements', {
        'birthRightAccess': False, 'requestAccess': False,
        'additions': [{'assignee': {'subjectId': group['id'], 'subjectType': 'group'}, 'grantType': 'BRT'}]})
    # CIBA-only audience: ordinary login and client_credentials cannot mint a
    # matching human JWT. The JWT role grants policy on this token, not the entity.
    mounts = v('GET', 'sys/auth')
    if 'ciba-contract/' not in mounts:
        v('POST', 'sys/auth/ciba-contract', {'type': 'jwt', 'description': 'Lumen CIBA contract confirmation'})
    elif mounts['ciba-contract/']['type'] != 'jwt':
        raise RuntimeError('ciba-contract is not a JWT auth mount.')
    v('POST', 'auth/ciba-contract/config', {'jwks_url': TENANT + '/oauth2/jwks',
        'bound_issuer': TENANT + '/oauth2', 'jwt_supported_algs': ['RS256']})
    for policy in ('confirm', 'owner', 'ceiling'):
        v('PUT', 'sys/policies/acl/lumen-contract-' + policy,
          {'policy': (ROOT / 'chatbot/policies' / ('contract-' + policy + '.hcl')).read_text()})
    v('POST', 'auth/ciba-contract/role/validator', {'role_type': 'jwt', 'user_claim': 'sub',
        'bound_subject': uid, 'bound_audiences': [cid], 'jwt_supported_algs': ['RS256'],
        'token_policies': ['lumen-contract-confirm', 'lumen-block-database-read',
                           'lumen-block-database-write', 'lumen-block-decrypt'], 'token_no_default_policy': True,
        'token_ttl': 120, 'token_max_ttl': 120, 'token_explicit_max_ttl': 120})
    # Preserve active global blocks when extending an existing installation.
    for target in ('database-read', 'database-write'):
        path = 'sys/policies/acl/lumen-block-' + target
        block = v('GET', path, missing=True)
        if block and '"deny"' in block['policy'] and 'database/creds/chatbot-contract' not in block['policy']:
            v('PUT', path, {'policy': block['policy'] + '\npath "database/creds/chatbot-contract" { capabilities = ["deny"] }\n'})
    if v('GET', 'transit/keys/lumen-contracts', missing=True) is None:
        v('POST', 'transit/keys/lumen-contracts', {'type': 'aes256-gcm96', 'exportable': False})
    result = subprocess.run(['kubectl', '--context', 'workshop', '-n', 'mysql', 'exec', '-i',
        'mysql-enterprise-0', '-c', 'mysql', '--', 'sh', '-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4'],
        input=(ROOT / 'chatbot/config/contracts.sql').read_text(), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Contract schema setup failed: ' + result.stderr[-1500:])
    connection = v('GET', 'database/config/chatbot-mysql')
    v('POST', 'database/config/chatbot-mysql', {'allowed_roles': list(dict.fromkeys([
        *connection['allowed_roles'], 'chatbot-contract']))})
    public_columns = 'application_id,contract_id,requestor_subject,owner_entity,validator_subject,status,confirmed_at,plan_name,price_kwh,snapshot_hash,pdf_sha256'
    for role in ('readonly', 'readwrite'):
        value = v('GET', 'database/roles/chatbot-' + role)
        statements = [sql for sql in value['creation_statements'] if 'lumen_contracts.contracts' not in sql]
        # Keep original grants while adding only non-sensitive contract metadata.
        statements.append("GRANT SELECT(" + public_columns + ") ON lumen_contracts.contracts TO '{{name}}'@'%';")
        value['creation_statements'] = statements
        v('POST', 'database/roles/chatbot-' + role, value)
    v('POST', 'database/roles/chatbot-contract', {'db_name': 'chatbot-mysql',
        'creation_statements': ["CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}'; GRANT EXECUTE ON PROCEDURE lumen_contracts.formalize TO '{{name}}'@'%';"],
        'revocation_statements': ["DROP USER IF EXISTS '{{name}}'@'%';"], 'default_ttl': '60s', 'max_ttl': '120s'})
    writers = []
    for entity_id in v('GET', 'identity/group/name/chatbot-writers')['member_entity_ids']:
        entity = v('GET', 'identity/entity/id/' + entity_id)
        subject = entity.get('external_id') or entity['name'].removeprefix('chatbot-human-')
        writers.append({'subject': subject, 'entity_id': entity_id, 'name': entity['name']})
    v('POST', 'identity/group/name/lumen-contract-writers', {'type': 'internal',
        'policies': ['lumen-contract-owner'], 'member_entity_ids': [u['entity_id'] for u in writers]})
    for suffix in ('oidc', 'task-read', 'task-write', 'task-reveal'):
        registration = v('GET', 'agent-registry/registration/display-name/chatbot-' + suffix, missing=True)
        if registration:
            body = {k: registration[k] for k in ('display_name','entity_id','description',
                'no_default_ceiling_policy','optional_authorization_details') if k in registration}
            body['ceiling_policies'] = list(dict.fromkeys([*registration['ceiling_policies'], 'lumen-contract-ceiling']))
            v('POST', 'agent-registry/register', body)
    user_detail = api('GET', '/v2.0/Users/' + uid)
    realm = user_detail.get('urn:ietf:params:scim:schemas:extension:ibm:2.0:User', {}).get('realm')
    if not realm:
        raise RuntimeError('Validator identity source realm is missing.')
    hint_username = username.removesuffix('@' + realm) if realm != 'cloudIdentityRealm' else username
    previous = kv('contracts', missing=True) or {}
    enabled = (previous.get('version') == 2 and previous.get('enabled', False)
               and previous.get('validator_subject') == uid and previous.get('client_id') == cid)
    if enable:
        evidence = json.loads((ROOT / 'chatbot/docs/contracts-verification.json').read_text())
        if evidence.get('flow') != 'contract-ciba' or evidence.get('passed') is not True or evidence.get('validator_subject') != uid or evidence.get('client_id') != cid:
            raise RuntimeError('Run verify-contracts.sh with the selected validator before enabling.')
        enabled = True
    kv('contracts', {'version': 2, 'enabled': enabled, 'client_id': cid,
        'client_secret': updated['properties']['clientSecret'], 'application_id': aid,
        'validator_subject': uid, 'validator_username': username, 'validator_group': group['id'],
        'validator_login_hint': {'username': hint_username, 'realm': realm},
        'delivery_mode': 'poll', 'auth_mount': 'ciba-contract', 'database_role': 'chatbot-contract',
        'writers': writers})
    v('PUT', 'sys/policies/acl/chatbot-bootstrap',
      {'policy': (ROOT / 'chatbot/policies/bootstrap.hcl').read_text()})
    v('PUT', 'sys/policies/acl/chatbot-agent-inspector',
      {'policy': (ROOT / 'chatbot/policies/agent-inspector.hcl').read_text()})
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_path.write_text(json.dumps({'username': username}) + '\n')
    state_path.chmod(0o600)
    print('Validator and CIBA client prepared. Contracting: ' + ('enabled' if enabled else 'disabled until validation') + '.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--validator', help='Existing Verify username; no password or profile changes')
    parser.add_argument('--enable', action='store_true', help='Enable after the real CIBA/contract verification passed')
    args = parser.parse_args()
    with httpx.Client(base_url=os.environ['VAULT_ADDR'], timeout=30,
                      verify=ssl.create_default_context(cafile=os.environ['VAULT_CACERT']),
                      headers={'X-Vault-Token': os.environ['VAULT_TOKEN'], 'X-Vault-Namespace': 'verify'}) as vault, \
         httpx.Client(base_url=TENANT, timeout=30) as verify:
        configure(vault, verify, args.validator, args.enable)
