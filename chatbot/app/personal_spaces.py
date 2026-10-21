"""Personal KV v2 operations use real OBO tokens; Vault enforces ownership."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import re

from opentelemetry import trace
from .rar import LAB_CONTEXT, authorization_details
from .security import AccessDenied
from .services import VaultPermissionDenied, VaultResponseError
from .telemetry import span, trace_id

PREFIX = 'lumen-personal'


def configuration(config):
    value = config.get('personal-spaces', {})
    if value.get('version') != 1 or value.get('prefix') != PREFIX or not value.get('users'):
        raise AccessDenied('Los espacios personales todavía no están configurados.')
    return value


def owner_for(config, subject):
    matches = [u for u in configuration(config)['users'] if u['subject'] == subject]
    if len(matches) != 1 or not re.fullmatch(r'[a-f0-9-]{36}', matches[0]['entity_id']):
        raise AccessDenied('Tu identidad no tiene un espacio personal configurado.')
    return matches[0]


def secret_path(config, subject, name='demo', *, listing=False):
    entity = owner_for(config, subject)['entity_id']
    if listing:
        return f'secrets/metadata/{PREFIX}/{entity}/'
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise AccessDenied('Usa un nombre de 1 a 64 letras, números, guiones o guiones bajos.')
    return f'secrets/data/{PREFIX}/{entity}/{name}'


async def access(services, session, action, *, name='demo', value=None, version=0, target=None):
    session.require_login()
    owner = owner_for(services.config, session.subject)
    # Another configured demo owner is deliberately accepted for the isolation
    # probe: returning a local denial here would not prove Vault enforcement.
    target = target or session.subject
    target_owner = owner_for(services.config, target)
    if action not in ('read', 'write', 'list'):
        raise AccessDenied('Operación personal no válida.')
    path = secret_path(services.config, target, name, listing=action == 'list')
    caps = ['create', 'update'] if action == 'write' else ['list'] if action == 'list' else ['read']
    payload = None
    if action == 'write':
        if not isinstance(value, dict) or not value or len(json.dumps(value).encode()) > 8192:
            raise AccessDenied('Introduce un objeto JSON no vacío de hasta 8 KB.')
        if type(version) is not int or version < 0:
            raise AccessDenied('La versión del secreto no es válida.')
        payload = {'options': {'cas': version}, 'data': value}
    attrs = {'personal.action': action, 'personal.owner_entity': owner['entity_id'],
             'personal.target_entity': target_owner['entity_id'], 'personal.cross_user': target != session.subject,
             'personal.user_policy': 'lumen-personal-user', 'personal.path': path}
    context = LAB_CONTEXT.set({**LAB_CONTEXT.get(), **attrs})
    result = dict(action=action, path=path, owner=owner['name'], target=target_owner['name'],
                  expected=target == session.subject and (action != 'write' or session.task_agent in ('legacy', 'write')),
                  rar=authorization_details(path, caps), status=None, error='',
                  checked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    try:
        with span('personal.access') as current:
            result.update(trace_id=trace_id(), span_id=f'{current.get_span_context().span_id:016x}')
            token = await services.exchange(session, path, caps)
            try:
                if action == 'write':
                    data = await services.vault_post(path, token, payload)
                else:
                    data = await services.vault_get(path, token, params={'list': 'true'} if action == 'list' else None)
                result.update(status=200, data=data['data'])
            except VaultPermissionDenied:
                result.update(status=403, error='Vault ha denegado el acceso.')
            except VaultResponseError as exc:
                result.update(status=exc.status_code, error=(
                    'El secreto no existe.' if exc.status_code == 404 else
                    'La escritura no se ha aplicado. Recarga el secreto antes de volver a guardar.'
                    if exc.status_code == 400 and action == 'write' else 'Vault ha rechazado la operación.'))
    finally:
        LAB_CONTEXT.reset(context)
    services.event(session, 'Espacio personal', f'{action} · {result["status"] or "sin respuesta"}',
                   'ok' if result['status'] == 200 else 'error')
    return result
