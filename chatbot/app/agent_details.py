"""Live, read-only Vault metadata; separate from business and OBO credentials."""
from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlsplit

import httpx
import jwt

AGENT_NAMES = frozenset('chatbot-' + suffix for suffix in (
    'oidc', 'research', 'openai', 'anthropic', 'xai', 'task-read', 'task-write', 'task-reveal'))


def vault_ui_url(base, path, namespace='verify'):
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Invalid Vault UI address')
    return base.rstrip('/') + '/ui/vault/' + path + '?' + urlencode({'namespace': namespace})


def token_agent(token, config):
    """Telemetry attribution only. Authentication remains in Verify and Vault."""
    try:
        claims = jwt.decode(token, options={'verify_signature': False})
        subject = (claims.get('actor-token') or {}).get('sub') or claims.get('sub')
        return next((name for name in sorted(AGENT_NAMES)
                     if config.get(name.removeprefix('chatbot-'), {}).get('client_id') == subject and subject), '')
    except (jwt.InvalidTokenError, AttributeError, TypeError):
        return ''


class AgentInspector:
    def __init__(self, config, tls, token=None):
        self.config, self.tls = config, tls
        self._token = os.environ.pop('CHATBOT_AGENT_INSPECTOR_TOKEN', '') if token is None else token
        self.base = os.environ.get('LUMEN_VAULT_UI_URL', config['vault_addr']).rstrip('/')
        self._maintenance = None

    def start(self):
        if self._token:
            self._maintenance = asyncio.create_task(self._renew())

    async def _renew(self):
        while True:
            await asyncio.sleep(1200)
            try:
                async with self._client() as client:
                    await client.post('/v1/auth/token/renew-self', json={})
            except httpx.HTTPError:
                pass  # Metadata failures never change business authorization.

    async def close(self):
        if self._maintenance:
            self._maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await self._maintenance
        if self._token:
            with suppress(httpx.HTTPError):
                async with self._client() as client:
                    await client.post('/v1/auth/token/revoke-self')
            self._token = ''

    def _client(self):
        return httpx.AsyncClient(base_url=self.config['vault_addr'], verify=self.tls, timeout=10,
                                 headers={'X-Vault-Token': self._token, 'X-Vault-Namespace': 'verify'})

    async def describe(self, name):
        if name not in AGENT_NAMES:
            return None
        link = lambda path: vault_ui_url(self.base, path)
        result = {'name': name, 'namespace': 'verify', 'available': False,
                  'registry_url': link('agents/registry'), 'fields': [], 'entity_fields': [],
                  'aliases': [], 'policies': [], 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        if not self._token:
            result['message'] = 'Inspección de agentes no configurada. Reinicia Lumen con el script actualizado.'
            return result
        try:
            async with self._client() as client:
                async def read(path):
                    response = await client.get('/v1/' + path)
                    response.raise_for_status()
                    return response.json()['data']
                registration, entity = await asyncio.gather(
                    read('agent-registry/registration/display-name/' + quote(name, safe='')),
                    read('identity/entity/name/' + quote(name, safe='')))
                if registration['entity_id'] != entity['id']:
                    result['message'] = 'El registro y la entidad no coinciden. Revisa el agente en Vault.'
                    return result
                result.update(available=True, registry_id=registration['id'], entity_id=entity['id'],
                              entity_url=link('access/identity/entities/' + quote(entity['id'], safe='') + '/details'))
                result['fields'] = [
                    ['Descripción', registration.get('description', '')],
                    ['Estado de la entidad', 'Deshabilitada' if entity.get('disabled') else 'Habilitada'],
                    ['Agent registry ID', registration['id']], ['Namespace', 'verify'],
                    ['Propietario', registration.get('owner') or '/'],
                    ['Creado', registration.get('creation_time', '')],
                    ['Actualizado', registration.get('last_updated_time', '')],
                    ['RAR obligatorio', 'No' if registration.get('optional_authorization_details') else 'Sí'],
                    ['Techo default desactivado', 'Sí' if registration.get('no_default_ceiling_policy') else 'No'],
                ]
                result['entity_fields'] = [[label, entity.get(key, '')] for label, key in (
                    ('Nombre', 'name'), ('Entity ID', 'id'), ('Namespace ID', 'namespace_id'),
                    ('Creado', 'creation_time'), ('Actualizado', 'last_update_time'))]
                for key, label in [('direct_group_ids', 'Grupos directos'), ('inherited_group_ids', 'Grupos heredados')]:
                    result['entity_fields'].append([label, ', '.join(entity.get(key) or []) or 'Ninguno'])
                profile = {}
                try:
                    profile = await read('sys/config/oauth-resource-server/verify')
                except (httpx.HTTPError, ValueError, KeyError):
                    pass
                for alias in entity.get('aliases') or []:
                    # Deliberate projection: never expose entity MFA secrets or arbitrary metadata.
                    result['aliases'].append({
                        'name': alias['name'], 'id': alias['id'],
                        'url': link('access/identity/entities/aliases/' + quote(alias['id'], safe='') + '/details'),
                        'fields': [[label, alias.get(key, '')] for label, key in (
                            ('Alias ID', 'id'), ('Entity ID', 'canonical_id'), ('Mount accessor', 'mount_accessor'),
                            ('Creado', 'creation_time'), ('Actualizado', 'last_update_time'))],
                    })
                    accessor = alias.get('mount_accessor', '')
                    if profile.get('config_id') and accessor.endswith('_' + profile['config_id']):
                        result['aliases'][-1]['fields'] += [
                            ['Issuer', profile.get('issuer_id', '')], ['Perfil OAuth', 'verify'],
                            ['Profile ID', profile['config_id']]]
                if entity.get('group_ids'):
                    result['entity_fields'].append(['Políticas de grupo', 'Consulta los grupos en Vault; no se agregan aquí.'])
                levels = {}
                ceilings = list(registration.get('ceiling_policies') or [])
                if not registration.get('no_default_ceiling_policy'):
                    ceilings.append('default')
                for level, names in [('Techo OBO', ceilings), ('Política directa de la entidad', entity.get('policies') or [])]:
                    for policy in names:
                        levels.setdefault(policy, []).append(level)
                async def policy_detail(policy, level):
                    item = {'name': policy, 'levels': level,
                            'url': link('policy/acl/' + quote(policy, safe='')), 'available': False}
                    try:
                        data = await read('sys/policies/acl/' + quote(policy, safe=''))
                        item.update(available=True, hcl=data.get('policy', ''))
                    except (httpx.HTTPError, ValueError, KeyError):
                        pass
                    return item
                result['policies'] = await asyncio.gather(*(policy_detail(p, levels[p]) for p in sorted(levels)))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            result['message'] = 'No se pudieron consultar los metadatos actuales en Vault. Los resultados de permisos se muestran por separado.'
        return result

    async def describe_many(self, names):
        return dict(zip(sorted(names), await asyncio.gather(*(self.describe(n) for n in sorted(names)))))


def agent_markdown(detail, t):
    """Deterministic UI text, never model-generated or used as authorization evidence."""
    def cell(value):
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\n', ' ').replace('[', '&#91;').replace(']', '&#93;').replace('`', '&#96;').replace('_', '&#95;').replace('*', '&#42;').replace('\\', '&#92;')
    def table(fields):
        return ['| ' + t('Campo') + ' | ' + t('Valor') + ' |', '|---|---|'] + [
            f'| {t(label)} | {cell(t(value))} |' for label, value in fields]
    lines = ['**' + t('Agente en Vault') + ': ' + cell(detail['name']) + '**', '',
             '[' + t('Abrir Agent Registry') + '](' + detail['registry_url'] + ')', '',
             t('Metadatos consultados en Vault: {time}', time=detail['checked_at'])]
    if not detail['available']:
        return '\n'.join(lines + ['', t(detail['message'])])
    lines += ['', *table(detail['fields']), '', '**' + t('Detalles de la entidad') + '**', '',
              '[' + t('Abrir entidad en Vault') + '](' + detail['entity_url'] + ')', '', *table(detail['entity_fields']), '',
              '**' + t('Políticas del agente') + '**', '',
              '| ' + t('Nivel') + ' | Policy |', '|---|---|']
    for policy in detail['policies']:
        lines.append('| ' + ', '.join(t(level) for level in policy['levels']) + ' | [' + cell(policy['name']) + '](' + policy['url'] + ') |')
    if not any('Política directa de la entidad' in p['levels'] for p in detail['policies']):
        lines += ['', t('La entidad no tiene políticas directas. El techo OBO limita la delegación; no concede acceso autónomo.')]
    for alias in detail['aliases']:
        lines += ['', '**Alias: [' + cell(alias['name']) + '](' + alias['url'] + ')**', '', *table(alias['fields'])]
    lines += ['', t('Los metadatos describen la configuración. Los permisos efectivos se comprueban en las peticiones OBO de abajo.'),
              t('Los enlaces abren Vault con tu propia sesión; no incluyen tokens de Lumen.')]
    return '\n'.join(lines)
