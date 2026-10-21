"""RAR construction and trace context. Parameter restrictions never grant ACLs."""
from contextvars import ContextVar
from copy import deepcopy
import json

LAB_CONTEXT = ContextVar('rar_lab_context', default={})
PARAMETER_FIELDS = ('allowed_parameters', 'denied_parameters', 'required_parameters')


def authorization_details(path, capabilities=None, parameters=None):
    detail = {'type': 'vault:path_access', 'path': path, 'capabilities': capabilities or ['read']}
    if parameters is not None:
        if not isinstance(parameters, dict) or set(parameters) - set(PARAMETER_FIELDS):
            raise ValueError('Unknown RAR parameter control')
        for name, value in parameters.items():
            if name == 'required_parameters':
                valid = isinstance(value, list) and all(isinstance(k, str) and k for k in value)
                valid = valid and len(value) == len(set(value))
            else:
                valid = isinstance(value, dict) and all(isinstance(k, str) and k and isinstance(v, list)
                                                       for k, v in value.items())
            if not valid:
                raise ValueError('Invalid RAR parameter control: ' + name)
        # Reject non-JSON values and NaN rather than silently issuing a weaker RAR.
        encoded = json.dumps(parameters, allow_nan=False)
        if len(encoded.encode()) > 8192:
            raise ValueError('RAR parameter controls are too large')
        detail.update(deepcopy(parameters))
    return [detail]
