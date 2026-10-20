"""A credential-free view of recorded client calls, separate from local spans."""
from __future__ import annotations

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
                    request=f'Token exchange OBO · RAR para {path or "la ruta solicitada"}',
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
        return dict(target='vault', title=title, method=a.get('http.request.method', 'GET' if name != 'vault.write' else 'POST'),
                    endpoint='/v1/' + path, credential=credential,
                    request=f'Namespace {a.get("vault.namespace", "verify")} · {path}', response=response)
    if name == 'mysql.query':
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
        return dict(target=provider, title='Consultar el modelo', method='SDK',
                    endpoint=f'{a.get("gen_ai.request.model", "Modelo")} · API de inferencia',
                    credential='API key temporal de Vault' if provider == 'xai' else 'Access token de la federación SPIFFE',
                    request='Instrucciones, mensajes y definiciones de herramientas',
                    response='Texto y/o solicitudes de herramientas')
    if name == 'tavily.search':
        return dict(target='tavily', title='Buscar información pública', method='POST', endpoint='api.tavily.com/search',
                    credential='Credencial de Tavily obtenida de Vault',
                    request=f'Búsqueda pública · {a.get("search.topic", "tema")}',
                    response='Resultados y enlaces públicos')
    return None


def build_flow(records: list[dict]) -> dict:
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
            notes.append('Llamada lógica del SDK. La traza no desglosa sus reintentos ni captura aquí el cuerpo HTTP final.')
        state, status = _outcome(record)
        chain = ancestors(record)
        if description and name.endswith('.chat') and any(r['name'] == 'guardrail.energy_scope' for r in chain):
            description.update(title='Clasificar la pregunta',
                               request='Pregunta e instrucciones del control de ámbito',
                               response='Decisión de ámbito y operación solicitada')
        common = dict(id=record['span_id'], name=name, parent_id=record.get('parent_id'),
                      duration_ms=record['duration_ms'], start_ms=round((record['start_ns'] - start) / 1e6, 2),
                      state=state, status=status, context=' → '.join(r['name'] for r in chain))
        if description:
            code = attrs.get('http.response.status_code')
            calls.append(dict(**common, **description, source='lumen', notes=notes, sort_start=sort_start,
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
