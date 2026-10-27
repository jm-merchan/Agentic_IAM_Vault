"""Add isolated demo KV spaces without rewriting business ACLs or credentials."""
import os
from pathlib import Path
import ssl

import httpx

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'lumen-personal'
POLICIES = {name: (ROOT / 'policies' / f'personal-{name}.hcl').read_text()
            for name in ('user', 'read', 'write')}


def configure(client):
    def request(method, path, body=None, missing=False):
        response = client.request(method, '/v1/' + path, json=body)
        if missing and response.status_code == 404:
            return None
        if response.status_code not in (200, 204):
            # Never include a response body: other reads include directory credentials.
            raise RuntimeError(f'Vault HTTP {response.status_code}: {method} {path}')
        return response.json().get('data', {}) if response.content else {}

    mount = request('GET', 'sys/mounts')['secrets/']
    if mount['type'] != 'kv' or mount.get('options', {}).get('version') != '2':
        raise RuntimeError('The existing secrets KV v2 mount is required.')
    directory = request('GET', 'secrets/data/chatbot/directory')['data']['users']
    users = []
    for role in ('reader', 'writer', 'supervisor'):
        entries = [entry for entry in directory if entry['username'] == 'lumen-' + role]
        if len(entries) != 1:
            raise RuntimeError('Missing or duplicate user in the demo directory.')
        entry = entries[0]
        subject = entry['user_id']
        if not isinstance(subject, str) or not subject.isalnum():
            raise RuntimeError('Unexpected user identifier.')
        entity = request('GET', 'identity/entity/name/chatbot-human-' + subject)
        if entity.get('disabled') or entity.get('external_id') not in (None, subject):
            raise RuntimeError('Human entity disabled or mismatched.')
        users.append(dict(subject=subject, entity_id=entity['id'], name=entry['username'], role=role))
    registrations = []
    for suffix in ('oidc', 'task-read', 'task-write', 'task-reveal'):
        registration = request('GET', 'agent-registry/registration/display-name/chatbot-' + suffix,
                               missing=suffix != 'oidc')
        if registration is not None:
            registrations.append((suffix, registration))
    # All prerequisites resolved before mutation. Existing values are never reseeded.
    for name, policy in POLICIES.items():
        request('PUT', 'sys/policies/acl/lumen-personal-' + name, {'policy': policy})
    request('POST', 'identity/group/name/lumen-personal-users', {
        'type': 'internal', 'policies': ['lumen-personal-user'],
        'member_entity_ids': [user['entity_id'] for user in users]})
    for suffix, registration in registrations:
        policy = 'lumen-personal-' + ('write' if suffix in ('oidc', 'task-write') else 'read')
        payload = {k: registration[k] for k in (
            'display_name', 'entity_id', 'description', 'no_default_ceiling_policy',
            'optional_authorization_details') if k in registration}
        payload['ceiling_policies'] = list(dict.fromkeys([
            *registration.get('ceiling_policies', []), policy]))
        request('POST', 'agent-registry/register', payload)
    for user in users:
        path = f'secrets/data/{PREFIX}/{user["entity_id"]}/demo'
        if request('GET', path.replace('secrets/data/', 'secrets/metadata/', 1), missing=True) is None:
            # CAS 0 rejects overwriting an existing or deleted version.
            request('POST', path, {'options': {'cas': 0}, 'data': {
                'note': 'Dato ficticio de ' + user['name'], 'owner': user['name']}})
    config = dict(version=1, prefix=PREFIX, users=users, policies=POLICIES)
    request('POST', 'secrets/data/chatbot/personal-spaces', {'data': config})
    request('PUT', 'sys/policies/acl/chatbot-bootstrap', {
        'policy': (ROOT / 'policies/bootstrap.hcl').read_text()})
    print('Personal spaces ready; existing data preserved. Namespace: verify.')


if __name__ == '__main__':
    with httpx.Client(base_url=os.environ['VAULT_ADDR'], timeout=30,
                      verify=ssl.create_default_context(cafile=os.environ['VAULT_CACERT']),
                      headers={'X-Vault-Token': os.environ['VAULT_TOKEN'],
                               'X-Vault-Namespace': 'verify'}) as client:
        configure(client)
