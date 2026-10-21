"""Explanatory OBO matrix. This view never authorizes or executes operations."""
from __future__ import annotations

import time

from .security import role_for_groups
from .task_agents import TASK_AGENTS

OPERATIONS = {'read': 'Consultar', 'write': 'Crear solicitudes', 'reveal': 'Revelar datos'}
PROFILES = {
    'reader': ('Reader', frozenset({'read'})),
    'writer': ('Writer', frozenset({'read', 'write'})),
    'supervisor': ('Supervisor', frozenset({'read', 'reveal'})),
}
AGENTS = {'legacy': 'Estándar', **{key: task['label'] for key, task in TASK_AGENTS.items()}}


def agent_operations(mode):
    return frozenset(OPERATIONS) if mode == 'legacy' else TASK_AGENTS.get(mode, {}).get('operations', frozenset())


def current_profile(config, session):
    """Derive the displayed profile from authenticated groups, never the name."""
    if not session or not session.subject or session.expires_at <= time.time():
        return None
    mapping = config.get('runtime', {}).get('groups', {})
    role = role_for_groups(session.groups, mapping)
    operations = set()
    if role:
        operations.add('read')
    if role == 'readwrite':
        operations.add('write')
    if set(session.groups).intersection(mapping.get('sensitive', [])):
        operations.add('reveal')
    for key, (label, expected) in PROFILES.items():
        if operations == expected:
            return key, label, frozenset(operations)
    return 'session', 'Perfil combinado' if operations else 'Sin acceso a datos', frozenset(operations)


def decisions(user_operations, mode):
    ceiling = agent_operations(mode)
    return [dict(operation=operation, label=label, user=operation in user_operations,
                 agent=operation in ceiling, expected=operation in user_operations and operation in ceiling)
            for operation, label in OPERATIONS.items()]


def summary(user_operations, mode, t):
    allowed = user_operations & agent_operations(mode)
    text = {
        frozenset({'read'}): 'Consultar',
        frozenset({'read', 'write'}): 'Consultar y crear',
        frozenset({'read', 'reveal'}): 'Consultar y revelar',
        frozenset({'read', 'write', 'reveal'}): 'Consultar, crear y revelar',
    }.get(frozenset(allowed), 'Sin acceso a datos')
    return t(text)
