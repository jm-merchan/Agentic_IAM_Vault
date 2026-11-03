"""Approval-scoped OAuth permissions for the dedicated CIBA client."""
import json
from .rar import authorization_details

ACTOR_NAME = 'chatbot-contract'
CONFIG_VERSION = 3


def same_permissions(issued, requested):
    """Verify may reorder consent entries; preserve their complete constraints."""
    def canonical(details):
        if not isinstance(details, list):
            raise ValueError('RAR must be a list')
        result = []
        for detail in details:
            value = dict(detail)
            for key in ('capabilities', 'required_parameters'):
                if key in value:
                    if not isinstance(value[key], list) or not all(isinstance(v, str) for v in value[key]):
                        raise ValueError('Invalid RAR constraint')
                    value[key] = sorted(value[key])
            result.append(json.dumps(value, sort_keys=True, allow_nan=False))
        return sorted(result)
    try:
        return canonical(issued) == canonical(requested)
    except (TypeError, ValueError):
        return False


def permissions(owner_entity, contract_id):
    """The signed RAR names one owner's PDF and the required engine operations."""
    details = []
    # Verify accepts at most five details. Engine globs are intersected with
    # exact human/actor ACL paths; the PDF detail remains owner/contract-exact.
    for path in ('transit/*', 'transform/decode/lumen-*'):
        details += authorization_details(path, ['update'])
    details += authorization_details('database/creds/chatbot-contract', ['read'])
    details += authorization_details(
        f'secrets/data/lumen-contracts/{owner_entity}/{contract_id}',
        ['create', 'read', 'update'],
    )
    details += authorization_details('auth/token/revoke', ['update'], {
        'allowed_parameters': {'token': []}, 'required_parameters': ['token'],
    })
    return details
