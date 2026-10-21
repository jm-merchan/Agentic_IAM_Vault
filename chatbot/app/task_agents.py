"""Optional task identities. Selection is bound to a fresh OIDC session."""
from __future__ import annotations

TASK_AGENTS = {
    'read': {
        'credential': 'task-read', 'label': 'Consulta',
        'description': 'Consulta tarifas, inventario y solicitudes enmascaradas. No crea ni revela datos.',
        'operations': frozenset({'read'}),
    },
    'write': {
        'credential': 'task-write', 'label': 'Creación de solicitudes',
        'description': 'Consulta y crea solicitudes con datos protegidos. No revela datos.',
        'operations': frozenset({'read', 'write'}),
    },
    'reveal': {
        'credential': 'task-reveal', 'label': 'Revelado de datos',
        'description': 'Consulta y revela datos si tu usuario tiene permiso. No crea solicitudes.',
        'operations': frozenset({'read', 'reveal'}),
    },
}


def task_allows(session, operation: str) -> bool:
    mode = getattr(session, 'task_agent', 'legacy')
    return mode == 'legacy' or operation in TASK_AGENTS.get(mode, {}).get('operations', ())


def actor_credential(config: dict, mode: str) -> str:
    from .security import AccessDenied
    if mode == 'legacy':
        return 'oidc'
    if mode not in TASK_AGENTS or not task_agents_ready(config):
        raise AccessDenied('Los agentes por tarea todavía no están configurados.')
    return TASK_AGENTS[mode]['credential']


def task_agents_ready(config: dict) -> bool:
    return all(
        isinstance(config.get(task['credential']), dict)
        and all(isinstance(config[task['credential']].get(key), str)
                and config[task['credential']][key] for key in ('client_id', 'client_secret'))
        for task in TASK_AGENTS.values()
    )


def task_label(session) -> str:
    return TASK_AGENTS.get(getattr(session, 'task_agent', 'legacy'), {}).get('label', 'Modo actual')
