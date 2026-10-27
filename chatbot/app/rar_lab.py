"""Explicit, synthetic OBO comparisons; every access decision comes from Vault."""
from contextlib import contextmanager
import base64
import json

from .rar import LAB_CONTEXT, authorization_details
from .security import AccessDenied
from .telemetry import span, trace_id
from .task_agents import actor_credential


def _b64(text):
    return base64.b64encode(text.encode()).decode()


def scenarios(config):
    """Fresh JSON objects: UI edits or a previous run cannot alter future rules."""
    approved, blocked, other = map(_b64, ('lumen-rar-approved', 'lumen-rar-blocked', 'lumen-rar-other'))
    encrypt = 'transit/encrypt/lumen-applications'
    def case(key, label, payload, expected, reason):
        return dict(id=key, label=label, payload=payload, expected=expected, reason=reason)
    items = [
        dict(id='allowed', title='Permitir una versión de cifrado', operation='write', path=encrypt,
             description='allowed_parameters limita los nombres y valores admitidos. [] acepta cualquier valor de ese parámetro; los campos no enumerados quedan fuera.',
             parameters={'allowed_parameters': {'plaintext': [], 'key_version': ['1']}},
             cases=[
                 case('version-one', 'Versión permitida', {'plaintext': approved, 'key_version': '1'}, True, 'key_version coincide con la cadena "1" permitida.'),
                 case('version-default', 'Valor fuera de la lista', {'plaintext': approved, 'key_version': '0'}, False, '"0" selecciona la versión actual en Transit, pero no está permitido por este RAR.'),
                 case('extra-field', 'Campo no enumerado', {'plaintext': approved, 'key_version': '1', 'context': _b64('demo')}, False, 'context no figura en allowed_parameters.'),
                 case('numeric-value', 'Número frente a cadena', {'plaintext': approved, 'key_version': 1}, False, 'Se compara el valor JSON exacto: 1 y "1" tienen tipos distintos. Consulta el resultado real de esta versión de Vault.'),
             ]),
        dict(id='denied', title='Prohibir el cifrado por lotes', operation='write', path=encrypt,
             description='denied_parameters con [] prohíbe la presencia del parámetro, cualquiera que sea su valor. Aquí se permite cifrar un dato, pero se prohíbe batch_input.',
             parameters={'denied_parameters': {'batch_input': []}}, cases=[
                 case('single', 'Un solo dato', {'plaintext': approved}, True, 'La petición no contiene batch_input.'),
                 case('batch', 'Dos datos en un lote', {'batch_input': [{'plaintext': approved}, {'plaintext': other}]}, False, 'La petición contiene el parámetro prohibido batch_input.'),
             ]),
        dict(id='required', title='Exigir una versión explícita', operation='write', path=encrypt,
             description='required_parameters exige presencia, no un valor concreto. Transit admite omitir key_version; este RAR obliga a enviarlo.',
             parameters={'required_parameters': ['key_version']}, cases=[
                 case('present', 'Parámetro presente', {'plaintext': approved, 'key_version': '1'}, True, 'key_version está presente.'),
                 case('absent', 'Parámetro omitido', {'plaintext': approved}, False, 'Falta key_version, aunque Transit lo acepte sin esta restricción.'),
                 case('zero', 'Otro valor presente', {'plaintext': approved, 'key_version': '0'}, True, 'required_parameters solo exige presencia; no impone la versión 1.'),
             ]),
        dict(id='combined', title='Combinar las tres restricciones', operation='write', path=encrypt,
             description='Se permiten dos mensajes ficticios y la versión "1", se prohíbe uno de esos mensajes y se exige key_version. La denegación prevalece sobre la lista permitida.',
             parameters={'allowed_parameters': {'plaintext': [approved, blocked], 'key_version': ['1']},
                         'denied_parameters': {'plaintext': [blocked]}, 'required_parameters': ['key_version']}, cases=[
                 case('approved', 'Cumple las tres reglas', {'plaintext': approved, 'key_version': '1'}, True, 'Valor permitido, no prohibido y parámetro obligatorio presente.'),
                 case('deny-wins', 'Permitido y prohibido a la vez', {'plaintext': blocked, 'key_version': '1'}, False, 'denied_parameters prevalece aunque el valor también aparezca en allowed_parameters.'),
                 case('required-missing', 'Falta el parámetro obligatorio', {'plaintext': approved}, False, 'Falta key_version.'),
                 case('outside-allow', 'Mensaje fuera de la lista', {'plaintext': other, 'key_version': '1'}, False, 'plaintext no coincide con ninguno de los valores permitidos.'),
             ]),
        dict(id='transform', title='Exigir la transformación elegida', operation='write', path='transform/encode/lumen-dni',
             description='La ruta tiene una única transformación configurada. El RAR exige indicar transformation explícitamente, aunque el motor pueda deducirla.',
             parameters={'required_parameters': ['transformation']}, cases=[
                 case('explicit', 'Transformación explícita', {'value': 'lumen-rar-synthetic-document', 'transformation': 'lumen-dni'}, True, 'transformation está presente.'),
                 case('implicit', 'Transformación implícita', {'value': 'lumen-rar-synthetic-document'}, False, 'Falta transformation en el cuerpo de la petición.'),
             ]),
    ]
    fixture = config.get('runtime', {}).get('rar_probe', {})
    if fixture.get('version') == 1 and all(isinstance(fixture.get(k, {}).get('ciphertext'), str) for k in ('approved', 'other')):
        items.append(dict(id='decrypt', title='Delegar el revelado de un solo perfil', operation='reveal',
            path='transit/decrypt/lumen-applications',
            description='El RAR permite únicamente el ciphertext ficticio aprobado. Los permisos de Supervisor y el techo del agente siguen siendo necesarios.',
            parameters={'allowed_parameters': {'ciphertext': [fixture['approved']['ciphertext']]},
                        'required_parameters': ['ciphertext']}, cases=[
                case('approved-profile', 'Perfil aprobado', {'ciphertext': fixture['approved']['ciphertext']}, True, 'El ciphertext coincide con el valor aprobado.'),
                case('other-profile', 'Otro perfil válido', {'ciphertext': fixture['other']['ciphertext']}, False, 'El ciphertext es válido, pero corresponde a otro perfil ficticio.'),
            ]))
    return {item['id']: item for item in items}


@contextmanager
def _context(attributes):
    handle = LAB_CONTEXT.set(attributes)
    try:
        yield
    finally:
        LAB_CONTEXT.reset(handle)


def interpretation(baseline, restricted, expected):
    """A 403 alone cannot identify the layer which rejected a request."""
    if baseline == 200 and restricted == (200 if expected else 403):
        return 'allowed' if expected else 'rar_denied'
    if baseline == 403 and restricted == 403:
        return 'baseline_denied'
    if baseline == 200 and restricted == 200 and not expected:
        return 'not_enforced'
    if baseline == 200 and restricted == 403 and expected:
        return 'unexpected_denial'
    return 'inconclusive'


INTERPRETATIONS = {
    'allowed': 'Permitido con las restricciones',
    'rar_denied': 'Denegación atribuible al RAR: control 200, restringida 403',
    'baseline_denied': 'También falla el control: revisar usuario, techo del agente y bloqueos',
    'not_enforced': 'La restricción no se ha aplicado como se esperaba',
    'unexpected_denial': 'Denegación inesperada con las restricciones',
    'inconclusive': 'No concluyente: revisar la respuesta o el intercambio OBO',
}


async def run_comparison(services, session, scenario_id, case_id, on_result=None):
    """Same payload and identity, two independently validated OBO tokens."""
    from .services import VaultPermissionDenied, VaultResponseError
    services.role(session)
    available = scenarios(services.config)
    if scenario_id not in available:
        raise AccessDenied('El escenario RAR no está disponible. Revisa la preparación del laboratorio.')
    scenario = available[scenario_id]
    chosen = [case for case in scenario['cases'] if case_id in ('all', case['id'])]
    if not chosen:
        raise AccessDenied('El caso RAR no es válido.')
    agent = 'chatbot-' + actor_credential(services.config, session.task_agent)
    results = []
    for case in chosen:
        result = dict(case=case['id'], label=case['label'], expected=case['expected'], reason=case['reason'],
                      payload=case['payload'], trace_id=trace_id(), phases={})
        for phase, parameters in [('baseline', None), ('restricted', scenario['parameters'])]:
            session.require_login()
            details = authorization_details(scenario['path'], ['update'], parameters)
            attributes = {'agent.identity': agent, 'rar.lab.scenario': scenario['title'], 'rar.lab.case': case['label'],
                          'rar.lab.phase': phase, 'rar.lab.authorization_details': json.dumps(details),
                          'rar.lab.payload': json.dumps(case['payload']), 'rar.lab.expected': case['expected']}
            with _context(attributes), span('rar.comparison.phase') as current:
                phase_result = dict(status=None, span_id='', error='', authorization_details=details)
                try:
                    token = await services.exchange(session, scenario['path'], ['update'], parameters=parameters)
                    # The direct child records the actual Vault request and its response.
                    with span('rar.comparison.access') as access:
                        phase_result['span_id'] = f'{access.get_span_context().span_id:016x}'
                        try:
                            response = await services.vault_post(scenario['path'], token, case['payload'])
                            phase_result['status'] = 200
                            phase_result['request_id'] = response.get('request_id', '')
                        except VaultPermissionDenied:
                            phase_result['status'] = 403
                        except VaultResponseError as exc:
                            phase_result['status'] = exc.status_code
                    current.set_attribute('rar.lab.vault_status', phase_result['status'])
                except AccessDenied as exc:
                    # Do not label a token issuance/validation failure as a Vault denial.
                    phase_result['error'] = str(exc)
                except Exception as exc:
                    phase_result['error'] = 'Error de conexión o ejecución; consulta la traza.'
                    current.set_attribute('error.type', type(exc).__name__)
                result['phases'][phase] = phase_result
        result['interpretation'] = interpretation(result['phases']['baseline']['status'],
                                                  result['phases']['restricted']['status'], case['expected'])
        results.append(result)
        if on_result:
            on_result(result)
    services.event(session, 'Comparación RAR', scenario['title'])
    return results
