"""A credential-free view of recorded client calls, separate from local spans."""
from __future__ import annotations
import json
import re

ACTORS = {
    'lumen': ('Lumen', 'Aplicación · orquesta las llamadas'),
    'verify': ('IBM Verify', 'Identidad y delegación'),
    'vault': ('Vault', 'Credenciales y protección'),
    'mysql': ('MySQL', 'Datos de la demo'),
    'openai': ('OpenAI', 'Federación y modelo'),
    'anthropic': ('Claude', 'Federación y modelo'),
    'xai': ('xAI', 'Modelo'),
    'tavily': ('Tavily', 'Búsqueda pública'),
}
TITLES = {
    'lumen.contract.request': 'Solicitar contratación con CIBA',
    'lumen.contract.confirm': 'Confirmar y formalizar el contrato',
    'lumen.contract.validate_validator': 'Validar la identidad de Validador',
    'lumen.contract.download': 'Descargar contrato registrado',
    'lumen.personal.read': 'Leer un espacio personal',
    'lumen.personal.write': 'Guardar en un espacio personal',
    'lumen.personal.list': 'Listar un espacio personal',
    'personal.access': 'Comprobar la política del propietario',
    'lumen.rar.compare': 'Comparación de parámetros RAR',
    'rar.comparison.phase': 'Preparar una fase de la comparación RAR',
    'rar.comparison.access': 'Comprobar el acceso en Vault',
    'lumen.applications.list': 'Consultar solicitudes',
    'lumen.application.save': 'Guardar solicitud',
    'lumen.action': 'Ejecución de Lumen',
    'deepagents.run': 'Conversación con el agente',
    'application.list_masked': 'Preparar la bandeja enmascarada',
    'data.access': 'Coordinar el acceso a los datos',
    'model.credentials': 'Preparar la credencial del modelo',
    'spiffe.mint_jwt_svid': 'Emitir y validar la identidad SPIFFE',
    'guardrail.energy_scope': 'Comprobar el ámbito de la pregunta',
    'verify.obo_exchange': 'Preparar y validar la delegación OBO',
}


def _outcome(record):
    attrs = record.get('attributes', {})
    code = attrs.get('http.response.status_code')
    if attrs.get('auth.ciba.result') in ('authorization_pending', 'slow_down'):
        return 'normal', 'Pendiente de aprobación CIBA'
    failed = record.get('status') == 'ERROR' or (isinstance(code, (int, float)) and code >= 400)
    label = ('Error · ' if failed else '') + (f'HTTP {code}' if code else 'sin código HTTP')
    if not code:
        label = 'Error registrado' if failed else 'Sin error registrado'
    return 'error' if failed else 'normal', label


def _describe(record):
    name, a = record['name'], record.get('attributes', {})
    path = a.get('vault.path', '')
    # Only declared fields are projected. Raw tokens, headers, messages and SQL
    # parameters never enter the diagram's browser payload.
    if name in {'verify.ciba_start', 'verify.ciba_poll'}:
        return dict(target='verify', title='Solicitar aprobación CIBA' if name.endswith('start') else 'Consultar aprobación CIBA',
                    method='POST', endpoint='/oauth2/ciba' if name.endswith('start') else '/oauth2/token',
                    credential='Cliente confidencial de contratación CIBA',
                    request='Identidad de Validador y referencia del borrador' if name.endswith('start') else 'auth_req_id de esta petición',
                    response='Petición pendiente; todavía no formaliza el contrato' if name.endswith('start') else 'Estado o tokens de Validador tras su confirmación')
    if name == 'verify.client_credentials':
        return dict(target='verify', title='Autenticar al agente', method='POST', endpoint='/oauth2/token',
                    credential='Client ID y secreto del agente',
                    request=f'Client Credentials · {a.get("agent.identity", "agente")}',
                    response='Access token del agente')
    if name == 'verify.oidc_login' and a.get('http.response.status_code'):
        return dict(target='verify', title='Completar el inicio de sesión', method='POST', endpoint='/oauth2/token',
                    credential='Cliente OIDC + código de autorización + verificador PKCE',
                    request='Canjear el código recibido del inicio de sesión',
                    response='Tokens de identidad y acceso del usuario')
    if name in {'verify.obo_exchange', 'verify.token_exchange'}:
        return dict(target='verify', title='Delegar el permiso del usuario', method='POST', endpoint='/oauth2/token',
                    credential='Cliente STS + token del usuario + token del agente',
                    request=(f'Token exchange OBO · RAR para {path or "la ruta solicitada"}'
                             + (f' · {a["agent.identity"]}' if a.get('agent.identity') else '')),
                    response='JWT delegado, limitado al usuario, al agente y a la ruta')
    if name in {'vault.read', 'vault.write', 'vault.jwks'}:
        response = 'Respuesta de la ruta de Vault'
        credential = 'JWT de Verify · X-Vault-Token'
        title = 'Leer de Vault' if name == 'vault.read' else 'Escribir en Vault'
        if name == 'vault.jwks':
            title, path = 'Obtener claves públicas SPIFFE', 'spiffe/.well-known/keys'
            credential, response = 'Sin token · claves públicas', 'JWKS para validar localmente la firma'
        elif path.startswith('database/creds/'):
            title, response = 'Obtener credenciales de MySQL', 'Usuario y contraseña temporales de MySQL'
            credential = 'JWT OBO de Verify · X-Vault-Token'
        elif path.endswith('/mintjwt'):
            title, response = 'Emitir identidad SPIFFE', 'JWT-SVID firmado por Vault'
        elif path.startswith('transit/'):
            title = 'Descifrar el perfil' if '/decrypt/' in path else 'Cifrar el perfil'
            credential = 'JWT OBO de Verify · X-Vault-Token'
        elif path.startswith('transform/'):
            title = 'Recuperar el dato protegido' if '/decode/' in path else 'Tokenizar el dato'
            credential = 'JWT OBO de Verify · X-Vault-Token'
        elif path.startswith('xai/creds/'):
            title, response = 'Emitir credencial de xAI', 'API key temporal de xAI'
        elif path == 'secrets/data/chatbot/xai-access':
            title, response = 'Autorizar el uso de xAI', 'Generación de autorización de la credencial'
        elif path == 'secrets/data/tavily':
            title, response = 'Obtener credencial de búsqueda', 'Credencial de Tavily'
        elif path.startswith(('secrets/data/lumen-personal/', 'secrets/metadata/lumen-personal/')):
            title = 'Listar un espacio personal' if '/metadata/' in path else 'Guardar en un espacio personal' if name == 'vault.write' else 'Leer un espacio personal'
            response = 'Respuesta KV del espacio solicitado'
            credential = 'JWT OBO de Verify · X-Vault-Token'
        elif path.startswith('secrets/data/lumen-contracts/'):
            title = 'Publicar el contrato PDF' if name == 'vault.write' else 'Leer el contrato PDF'
            credential = 'JWT OBO de Verify · X-Vault-Token'
            response = 'Contrato PDF vinculado a su propietario'
        if a.get('auth.flow') == 'ciba_jwt':
            credential = 'Token nativo de Vault obtenido con CIBA · X-Vault-Token'
        if path == 'auth/ciba-contract/login':
            title, credential, response = ('Validar CIBA en Vault', 'ID token de Validador emitido por el cliente CIBA',
                'Token nativo de Vault · política lumen-contract-confirm')
        elif path == 'database/creds/chatbot-contract':
            title, response = 'Obtener credencial de contratación', 'Usuario temporal con EXECUTE sobre lumen_contracts.formalize'
        elif path in ('transit/encrypt/lumen-contracts', 'transit/decrypt/lumen-contracts'):
            title = 'Cifrar el contrato PDF' if '/encrypt/' in path else 'Recuperar el contrato PDF registrado'
        elif path == 'auth/token/revoke-self':
            title, response = 'Revocar la credencial CIBA de Vault', 'Token y credenciales SQL dependientes revocados'
        return dict(target='vault', title=title, method=a.get('http.request.method', 'GET' if name != 'vault.write' else 'POST'),
                    endpoint='/v1/' + path, credential=credential,
                    request=f'Namespace {a.get("vault.namespace", "verify")} · {path}', response=response)
    if name == 'mysql.query':
        if a.get('db.role') == 'contract':
            return dict(target='mysql', title='Formalizar contrato', method='CALL', endpoint='lumen_contracts.formalize',
                        credential='Credencial temporal de Vault · rol chatbot-contract · EXECUTE',
                        request='Borrador, propietario, Validador y hashes del contenido y del PDF',
                        response='Commit de status = contratada y referencia del contrato')
        return dict(target='mysql', title='Consultar datos' if a.get('db.operation.name') == 'SELECT' else 'Modificar datos',
                    method=a.get('db.operation.name', 'SQL'), endpoint=a.get('db.namespace', 'MySQL'),
                    credential=f'Credencial temporal de Vault · rol {a.get("db.role", "no registrado")}',
                    request='Consulta SQL desde el servidor de Lumen',
                    response='Filas de la consulta' if a.get('db.operation.name') == 'SELECT' else 'Resultado de la escritura')
    if name in {'openai.token_exchange', 'anthropic.token_exchange'}:
        provider = name.split('.')[0]
        return dict(target=provider, title='Intercambiar la identidad SPIFFE', method='POST',
                    endpoint='auth.openai.com/oauth/token' if provider == 'openai' else 'api.anthropic.com/v1/oauth/token',
                    credential='JWT-SVID firmado por Vault',
                    request='subject_token + mapping de la cuenta' if provider == 'openai' else 'assertion de un solo uso + regla de federación',
                    response='Access token temporal del proveedor')
    if name in {'openai.chat', 'anthropic.chat', 'xai.chat'}:
        provider = name.split('.')[0]
        return dict(target=provider, title='Consultar el modelo', method=a.get('http.request.method', 'SDK'),
                    endpoint=(a.get('server.address', '') + a.get('url.path', '')) if a.get('lumen.http.attempts') else f'{a.get("gen_ai.request.model", "Modelo")} · API de inferencia',
                    credential='API key temporal de Vault' if provider == 'xai' else 'Access token de la federación SPIFFE',
                    request='Instrucciones, mensajes y definiciones de herramientas',
                    response='Texto y/o solicitudes de herramientas')
    if name == 'tavily.search':
        return dict(target='tavily', title='Buscar información pública', method='POST', endpoint='api.tavily.com/search',
                    credential='Credencial de Tavily obtenida de Vault',
                    request=f'Búsqueda pública · {a.get("search.topic", "tema")}',
                    response='Resultados y enlaces públicos')
    return None


def _personal_context(attrs):
    """Explain the demo's path template, without claiming to evaluate Vault ACLs.

    Identity and policy snapshots come from Lumen's provisioned catalogue. The
    actual authorization result remains the selected Vault call's HTTP status.
    Historical traces keep their recorded IDs; missing claims are never filled
    from today's configuration or from the requested resource owner's ID.
    """
    if not attrs.get('personal.path'):
        return None
    allowed = {'owner_entity', 'target_entity', 'user_policy', 'cross_user', 'path',
               'action', 'subject', 'issuer', 'owner_name', 'target_name', 'actor_client_id',
               'ceiling_policy', 'user_policy_snapshot', 'ceiling_policy_snapshot'}
    result = {key: attrs['personal.' + key] for key in allowed if 'personal.' + key in attrs}
    owner = result.get('owner_entity', '')
    path = result['path']
    match = re.fullmatch(r'(secrets/(data|metadata)/lumen-personal)/([a-f0-9-]{36})(/.*)?', path)
    if match and re.fullmatch(r'[a-f0-9-]{36}', owner):
        prefix, kind, requested_owner, suffix = match.groups()
        ending = '' if kind == 'metadata' and not suffix else '/*'
        result.update(template_path=prefix + '/{{identity.entity.id}}' + ending,
                      expanded_path=prefix + '/' + owner + ending,
                      path_matches_owner=requested_owner == owner)
    for attr, source in (('auth.rar.presented', 'presented'), ('auth.rar.requested', 'requested')):
        try:
            details = json.loads(attrs.get(attr, 'null'))
            if not isinstance(details, list):
                continue
            # Do not expose arbitrary RAR parameter values in the public diagram.
            projected = [{key: item[key] for key in ('type', 'path', 'capabilities') if key in item}
                         for item in details if isinstance(item, dict) and item.get('path') == path]
            if projected:
                result.update(authorization_details=projected, rar_source=source)
                break
        except (TypeError, ValueError):
            continue
    return result


def build_flow(records: list[dict], agent_details=None) -> dict:
    records = sorted(records, key=lambda r: (r['start_ns'], r.get('span_id', '')))
    start = min((r['start_ns'] for r in records), default=0)
    end = max((r['end_ns'] for r in records), default=start)
    by_id = {r['span_id']: r for r in records}
    children = {}
    for record in records:
        children.setdefault(record.get('parent_id'), []).append(record)

    def ancestors(record):
        chain, seen = [], {record['span_id']}
        while record.get('parent_id') in by_id and record['parent_id'] not in seen:
            record = by_id[record['parent_id']]
            chain.append(record)
            seen.add(record['span_id'])
        return list(reversed(chain))

    calls, local = [], []
    for record in records:
        name, attrs = record['name'], record.get('attributes', {})
        description = _describe(record)
        notes = []
        sort_start = record['start_ns']
        if name == 'verify.obo_exchange':
            nested = children.get(record['span_id'], [])
            # New traces measure the actual STS request in a separate child span.
            # Old traces prove a request only if they recorded an HTTP response.
            if any(r['name'] == 'verify.token_exchange' for r in nested) or not attrs.get('http.response.status_code'):
                description = None
            else:
                actor_calls = [r for r in nested if r['name'] == 'verify.client_credentials']
                sort_start = max([sort_start] + [r['end_ns'] for r in actor_calls])
                notes.append('Traza anterior: OBO incluye la obtención del token del agente. Se sitúa después de ese paso; su duración es inclusiva, no la latencia HTTP aislada.')
        if name.endswith('.chat'):
            notes.append('La consola incluye las peticiones HTTP reales de esta llamada y permite seleccionar cada intento.' if attrs.get('lumen.http.attempts') else 'Traza anterior sin captura HTTP del SDK. Los mensajes de telemetría no permiten reconstruir una petición exacta.')
        state, status = _outcome(record)
        chain = ancestors(record)
        rar_context = None
        if attrs.get('rar.lab.phase'):
            try:
                # Only this lab's synthetic inputs are shown by default. Other
                # capture values remain behind the existing inspection API.
                details = attrs.get('auth.rar.presented') or next(
                    (r.get('attributes', {}).get('auth.rar.validated') for r in reversed(chain)
                     if r.get('attributes', {}).get('auth.rar.validated')), None) or attrs.get('rar.lab.authorization_details', '[]')
                rar_context = dict(phase=attrs['rar.lab.phase'], scenario=attrs.get('rar.lab.scenario', ''),
                                   case=attrs.get('rar.lab.case', ''), authorization_details=json.loads(details),
                                   payload=json.loads(attrs.get('rar.lab.payload', '{}')))
            except (ValueError, TypeError):
                pass
        if description and name.endswith('.chat') and any(r['name'] == 'guardrail.energy_scope' for r in chain):
            description.update(title='Clasificar la pregunta',
                               request='Pregunta e instrucciones del control de ámbito',
                               response='Decisión de ámbito y operación solicitada')
        common = dict(id=record['span_id'], name=name, parent_id=record.get('parent_id'),
                      duration_ms=record['duration_ms'], start_ms=round((record['start_ns'] - start) / 1e6, 2),
                      state=state, status=status, context=' → '.join(r['name'] for r in chain))
        if description:
            # Prefer the identity recorded on this actual call. Provider and search
            # spans must never inherit the human's OBO actor from the root span.
            agent_name = attrs.get('agent.identity', '')
            if name == 'vault.jwks' or name.startswith('verify.ciba_') or attrs.get('auth.flow') == 'ciba_jwt':
                agent_name = ''
                if attrs.get('auth.flow') == 'ciba_jwt':
                    notes.append('Confirmación CIBA con autenticación JWT nativa de Vault. Esta llamada no utiliza OBO ni el techo del agente de la sesión.')
            elif not agent_name and name.split('.')[0] in {'openai', 'anthropic', 'xai'}:
                agent_name = 'chatbot-' + name.split('.')[0]
            elif not agent_name and name == 'tavily.search':
                agent_name = 'chatbot-research'
            elif not agent_name:
                agent_name = next((r['attributes']['agent.identity'] for r in reversed(chain)
                                   if r.get('attributes', {}).get('agent.identity')), '')
            from .agent_details import AGENT_NAMES
            if agent_name not in AGENT_NAMES:
                agent_name = ''
            code = attrs.get('http.response.status_code')
            calls.append(dict(**common, **description, agent_name=agent_name,
                              rar=rar_context,
                              personal=_personal_context(attrs),
                              approval={k: attrs['approval.' + k] for k in ('id', 'application', 'sha256', 'requestor', 'validator', 'operation')
                                        if 'approval.' + k in attrs} or None,
                              agent=(agent_details or {}).get(agent_name), source='lumen', notes=notes, sort_start=sort_start,
                              http_status=code, response_recorded=bool(code) or (
                                  state != 'error' and (name == 'mysql.query' or name.endswith('.chat'))),
                              request_id=attrs.get('vault.request_id', '')))
        else:
            local.append(dict(**common, title=TITLES.get(name, name), depth=len(chain)))
    calls.sort(key=lambda c: (c['sort_start'], c['start_ms'], c['id']))
    actor_ids = ['lumen']
    for i, call in enumerate(calls, 1):
        call['number'] = i
        del call['sort_start']
        if call['target'] not in actor_ids:
            actor_ids.append(call['target'])
    roots = [r for r in records if not r.get('parent_id')]
    root = roots[0] if roots else (records[0] if records else None)
    return dict(title=TITLES.get(root['name'], root['name']) if root else 'Traza sin registros disponibles',
                duration_ms=round((end - start) / 1e6, 2), calls=calls, local=local,
                actors=[dict(id=a, name=ACTORS[a][0], description=ACTORS[a][1]) for a in actor_ids],
                model_calls=sum(c['name'].endswith('.chat') for c in calls),
                local_errors=sum(r['state'] == 'error' for r in local),
                incomplete=any(r.get('parent_id') and r['parent_id'] not in by_id for r in records))
