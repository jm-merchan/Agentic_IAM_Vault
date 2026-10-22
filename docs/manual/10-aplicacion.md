# 10 · Arrancar Lumen y comprobar los recorridos

[Índice](README.md) · Requiere 00–05, [xAI](06-xai.md), [OpenAI](07-openai-spiffe.md) y [Claude](08-claude-spiffe.md), y [09](09-observabilidad.md)

## 1. Revisar la configuración que va a cargar la app


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
# Los perfiles se generan en 06 sección 6, 07 sección 7 y 08 sección 6.
# Ninguna de esas secciones cambia por sí sola el catálogo publicado.
initial=${LUMEN_MODEL_PROVIDER:-auto}
case "$initial" in auto) initial=openai;; openai|xai|anthropic) ;; *) echo 'Proveedor inicial no válido' >&2; exit 1;; esac
for provider in openai xai anthropic; do
  test -s "$MANUAL/model-$provider.json"
  vault kv metadata get -mount=secrets "chatbot/$provider" >/dev/null
done
jq -en --arg initial "$initial" \
  --slurpfile openai "$MANUAL/model-openai.json" \
  --slurpfile xai "$MANUAL/model-xai.json" \
  --slurpfile anthropic "$MANUAL/model-anthropic.json" '
  {openai:$openai[0],xai:$xai[0],anthropic:$anthropic[0]} as $profiles |
  if all($profiles|to_entries[];
    .key==.value.provider and (.value.model|type=="string" and length>0) and
    (.value|has("api_key")|not) and
    .value.credential_source==(if .key=="xai" then "vault_dynamic" else "vault_spiffe" end))
  then $profiles[$initial] + {providers:$profiles}
  else error("Perfil de proveedor no válido") end' > "$MANUAL/model-catalog.json"
# Solo se publica si los tres perfiles pasan la validación anterior.
vault kv put -mount=secrets chatbot/model - < "$MANUAL/model-catalog.json"
for name in oidc research sts runtime model openai xai anthropic; do
  vault kv metadata get -mount=secrets "chatbot/$name" >/dev/null
done
vault kv get -format=json -mount=secrets chatbot/model | \
  jq '.data.data|{initial:.provider,providers:(.providers|map_values({model,credential_source}))}'
vault read -format=json sys/config/oauth-resource-server/verify | \
  jq '.data|{issuer_id,use_jwks,user_claim,actor_claim,optional_authorization_details}'
```

Prepara previamente las tres identidades. El bloque anterior publica sus perfiles juntos en `chatbot/model` mediante Vault CLI; no crea identidades nuevas. Es el equivalente manual de `chatbot/scripts/configure-models.sh`, sin ejecutar el lanzador. El banner permite elegir OpenAI, xAI o Claude sin reiniciar, conserva la conversación y recuerda la preferencia. `LUMEN_MODEL_PROVIDER` o `--provider` solo fijan la selección inicial; `auto` utiliza OpenAI.

## 2. Instalar el runtime

```bash
uv venv --python 3.12 /tmp/vault-chatbot-venv
uv pip install --python /tmp/vault-chatbot-venv/bin/python -r chatbot/requirements.lock.txt
```

Si ese entorno ya existe, omitir `uv venv`. La lista bloqueada reproduce las dependencias del workspace: NiceGUI, Deep Agents, conectores de modelo, PyJWT, MySQL y OpenTelemetry. No se instala un framework distinto.

## 3. Crear bootstrap y arrancar sin credenciales administrativas

Comprobar que los forwards Vault, MySQL y observabilidad están activos. En una terminal dedicada, recargar el entorno al principio y ejecutar:

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json \
  -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m \
  -display-name=lumen-bootstrap | jq -er .auth.client_token)
vault policy write chatbot-agent-inspector "$LUMEN_ROOT/chatbot/policies/agent-inspector.hcl"
export CHATBOT_AGENT_INSPECTOR_TOKEN
CHATBOT_AGENT_INSPECTOR_TOKEN=$(vault token create -format=json -policy=chatbot-agent-inspector -no-default-policy -period=1h -display-name=lumen-agent-inspector | jq -er .auth.client_token)
unset VAULT_TOKEN
unset VERIFY_ADMIN_CLIENT_SECRET XAI_MANAGEMENT_API_KEY XAI_TEAM_ID TAVILY_API_KEY
unset OPENAI_ADMIN_API_KEY OPENAI_API_KEY NGROK_AUTHTOKEN
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE
unset ORACLE_REG_EMAIL ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD
unset LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
export LANGSMITH_TRACING=false
export LUMEN_TRACE_CONTENT=1
export LUMEN_TRACE_VAULT_RAW=1
export LUMEN_TRACE_CONTENT_MAX_BYTES=65536
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
export NICEGUI_STORAGE_PATH="$LUMEN_STATE_DIR/vault-chatbot-storage"
mkdir -p "$NICEGUI_STORAGE_PATH"
chmod 700 "$NICEGUI_STORAGE_PATH"
cd "$LUMEN_ROOT/chatbot"
/tmp/vault-chatbot-venv/bin/python -m app.main
```

La app carga su configuración y revoca el bootstrap en `load_config()`. Las operaciones de negocio usan JWT de Verify, OBO o identidad SPIFFE según el recurso. La ficha de agentes utiliza un token independiente de sólo lectura de metadatos, renovado por Lumen y revocado al cerrar; [alcance y enlaces](14-agentes-por-tarea.md#identificar-al-agente-y-pivotar-a-vault). No recargar `session.sh` dentro del proceso de la app después de limpiar sus variables.

Esta ejecución en primer plano se mantiene mientras la terminal esté abierta; Ctrl+C la detiene. El lanzador automatizado utiliza launchd y copia el runtime fuera de Google Drive por las restricciones de macOS. Esa supervisión no es necesaria para entender el arranque manual.

## 4. Abrir las interfaces

| Interfaz | URL / credencial |
|---|---|
| Lumen | `http://localhost:8088`, entrar con Verify → Cloud Directory |
| Vault | `https://127.0.0.1:8443/ui/`, Root token generado en 01 (`vault/config.env`), namespace `verify` |
| Grafana | `http://localhost:3000/d/lumen-iam`, `lumen-admin`, secreto `chatbot/observability` |

Para recuperar una contraseña humana en otra terminal, cargar [el entorno Vault](01-vault.md) y copiarla al portapapeles:

```bash
ROLE=reader
vault kv get -format=json -mount=secrets "chatbot/users/$ROLE" | jq -jr .data.data.password | pbcopy
```

Usar exactamente `localhost` para Lumen, no `127.0.0.1`, porque el callback está registrado con ese hostname. Cada cambio de usuario requiere cerrar sesión de Lumen y elegir otra cuenta en Verify; si persiste el SSO del anterior, cerrar su sesión Verify o utilizar un perfil privado de navegador.

### Idioma y comprobaciones bilingües

Las instrucciones de este manual usan etiquetas españolas. Pulsa **ES** si quieres seguirlas literalmente o usa sus equivalencias en inglés. El chat, formulario, bandeja y visor de trazas tienen **EN / ES** arriba a la derecha; la selección se recuerda en la cookie `lumen_language` durante un año y tiene prioridad sobre el navegador. Sin ella, se usa `Accept-Language` con variantes regionales y prioridades. Si no hay un idioma admitido se usa inglés; si falta la cabecera, español. [Detalle y equivalencias](../../chatbot/README.md#idioma-español-e-inglés).

1. **Detección inicial:** con un perfil sin la cookie `lumen_language`, abre Lumen con inglés como idioma preferido del navegador y comprueba la cabecera, la pantalla de Lumen antes de entrar y **EN** activo. Repite con español; debe quedar **ES**. Una sesión ya configurada mediante los botones no sirve para probar la detección inicial.
2. **Cambio manual:** pulsa EN y ES, recarga y navega entre chat, solicitudes y trazas. La elección debe mantenerse, también después del login. El cambio afecta a la siguiente respuesta del modelo; los mensajes anteriores conservan su idioma. Espera a que termine una operación antes de cambiar.
3. **Chat real:** elige **EN** y envía «What can you help me with? Answer in one sentence.» con OpenAI, xAI y Claude, esperando entre consultas. Deben responder en inglés. Vuelve a **ES** y pide «Dame un consejo breve para ahorrar energía en casa». Comprueba que el proveedor elegido y el historial se conservan.
4. **Catálogo y propuesta:** usa «Find your plan» o pregunta «Show the energy plans in Lumen's catalogue». Los títulos y descripciones deben aparecer en inglés, los nombres de las tarifas se conservan y los precios proceden de una consulta OBO actual. Como gestor, pide una propuesta para una tarifa concreta: **Continue application** abre el formulario; la propuesta aún no está guardada.
5. **Formulario:** como gestor, avanza al paso 2, pulsa **Continue** con los campos vacíos y comprueba el error en inglés. Escribe un valor ficticio en **Street**, cambia a ES y vuelve a EN: el valor y el paso deben conservarse. Los botones **Use test data**, **Save draft** y **Back to chat** equivalen a **Usar datos de prueba**, **Guardar borrador** y **Volver al chat**. Probar el idioma no requiere guardar una solicitud.
6. **Trazas:** genera una consulta nueva y abre **View latest trace**. Verifica destinos, detalles, números y paginación en inglés. En modo laboratorio, **View sensitive values** traduce los títulos de captura; el token, `client_secret`, SVID, credenciales dinámicas y cuerpos cifrados/descifrados siguen mostrando el valor original. Cambiar el idioma no amplía permisos ni revela automáticamente datos.
7. **Móvil:** comprueba que EN/ES sigue visible arriba a la derecha y que no aparece desplazamiento horizontal en el chat. El informe del 20/10 verificó un ancho de 390 px.

El portal de IBM Verify y Grafana conservan su propia configuración de idioma. Cambiar EN/ES conserva la sesión y el paso de traza enlazado mediante `?span=`; **reiniciar Lumen** termina la sesión y descarta conversaciones, formularios no guardados y capturas en memoria. [Resultados actuales y límites](../runs/20261022T140230Z-workspace-review/README.md); [comprobación bilingüe anterior del 20/10](VALIDACION.md#interfaz-bilingüe-y-trazas--20-de-octubre-de-2026).

## 5. Probar perfiles y resultados esperados

| Paso | Lector `lumen-reader` | Gestor `lumen-writer` | Supervisor `lumen-supervisor` |
|---|---|---|---|
| Consultar catálogo | Permitido, SQL RO | Permitido | Permitido |
| Comprobar límites Vault | RO sí; RW/protección no | RO/RW + encrypt/encode sí | RO + decrypt/decode sí |
| Crear solicitud de cinco pasos | Denegado | Permitido | Denegado |
| Leer la cola compartida del lab | Enmascarada | Enmascarada | Enmascarada hasta revelar |
| Revelar DNI/IBAN/perfil | Denegado | Denegado | Permitido |
| Leer secreto administrativo | Denegado | Denegado | Denegado |

Con gestor, pulsar **Usar datos de prueba**, revisar los cinco pasos de dirección, tarifa, identidad y pago, marcar la revisión y guardar. Anotar la referencia generada; no usar IDs de capturas históricas. Con lector y supervisor, abrir esa misma solicitud y contrastar lectura/revelado. La cola compartida de solicitudes es una decisión de este laboratorio; no se presenta como aislamiento por cliente/tenant.

## 6. Probar los dos flujos del agente

1. **Datos OBO:** pedir «Consulta las tarifas de electricidad del catálogo de Lumen». La traza debe incluir credenciales del proveedor, control de ámbito, `verify.obo_exchange`, `vault.read` en Database y `mysql.query` con SELECT. Una formulación explícita evita falsos rechazos del clasificador de ámbito de algunos modelos.
2. **Agente Tavily:** usar una de las búsquedas de energía ofrecidas por la UI. Se autentica como `chatbot-research`, lee `secrets/data/tavily` y llama a Tavily; no delega los permisos SQL del humano para esta búsqueda.
3. **Ámbito:** preguntar «¿Qué tiempo hace hoy en Palencia?» y después «venga». Debe mantenerse el rechazo de contenido ajeno a energía. Una pregunta posterior explícita sobre tarifas vuelve a admitirse. El primer filtro puede llamar al modelo. Cuando ese filtro marca la consulta como fuera de ámbito, el seguimiento corto se resuelve sin nuevas llamadas al modelo ni a Vault; compruébalo en la traza. Los proveedores pueden clasificar de forma distinta la primera pregunta: una respuesta textual de rechazo no demuestra por sí sola que no se haya llamado al modelo.
4. **Bloqueos:** aplicar el capítulo [12](12-bloqueos.md) y repetir una acción que antes funcionaba. Un error visible debe corresponder a un 403 Vault o a la revocación real, no únicamente a un texto generado por el modelo.

Repetir catálogo y control de ámbito con **OpenAI**, **xAI** y **Claude**, usando el banner entre consultas. Verificar que el modelo cambia, la conversación se conserva y el selector está bloqueado durante una respuesta. Abrir otra sesión para comprobar que su elección es independiente. Para OpenAI y Claude deben aparecer sus sujetos/roles SPIFFE respectivos; para xAI, la credencial dinámica. Las trazas del modelo deben indicar el proveedor elegido, no solo el inicial.

La salud del proceso debe enumerar las tres opciones. Esto comprueba la carga de configuración, no la disponibilidad de inferencia:

```bash
curl --fail --silent --show-error http://localhost:8088/health | \
  jq -e '.status=="ok" and ([.models[].provider]|sort)==["anthropic","openai","xai"]'
```

El banner identifica el proveedor y el modelo. La clasificación de ámbito y el system prompt limitan la conversación; **la autorización de datos la decide Vault**, no el LLM. [Guardrails y trazas](../ENERGY_SCOPE_AND_SVID.md).

## 7. Parar la ejecución manual

Detener Lumen y los port-forwards con Ctrl+C en sus terminales. Si se arrancó el publicador manual de JWKS, detener únicamente su PID después de comprobar que corresponde a ese proceso. Esto conserva los datos; no ejecutar `remove` como parte de una verificación de lectura.

La retirada completa ya está documentada en el [README principal](../../README.md) y `./demo.sh remove --dry-run` permite revisar su alcance. Esta serie explica configuración y comprobación; no requiere retirar un despliegue activo.

## Actualizar una instalación existente

### Solo interfaz, idioma y visor de trazas

Si los proveedores ya funcionan, el soporte EN/ES y el visor se incorporan con el código de la aplicación: `chatbot/app/`, incluido `translations_en.json`, y `chatbot/static/`. No hay nuevas variables de `.env`, identidades ni políticas por idioma. Tampoco hace falta volver a publicar `chatbot/model`.

- **Arranque manual en primer plano:** detener ese proceso con Ctrl+C y repetir la sección 3 con el código actualizado y un nuevo token bootstrap. Mantener los forwards e infraestructura existentes.
- **Arranque gestionado por el lanzador:** desde la raíz, ejecutar `bash scripts/demo/start.sh`. Actualiza la copia en `$LUMEN_STATE_DIR/runtime/chatbot`, renueva los forwards de observabilidad y reinicia Lumen. Requiere que la infraestructura existente siga activa.
- Volver a iniciar sesión y seguir las [comprobaciones bilingües](#idioma-y-comprobaciones-bilingües). El reinicio descarta el estado en memoria; la cookie de idioma del navegador y las solicitudes ya guardadas permanecen.

### Catálogo de los tres proveedores

No hace falta recrear Vault, usuarios, MySQL ni las federaciones para incorporar el selector. Si las tres identidades ya existen:

1. Cargar el entorno de la sección 1 y comprobar las variables `LUMEN_*_MODEL` de [00](00-entorno.md). Un valor antiguo en `.env` prevalece sobre los modelos por defecto.
2. Reaplicar únicamente la política bootstrap de [04, sección 6](04-vault-iam.md#6-política-bootstrap-y-comprobaciones), que ahora permite leer `chatbot/anthropic` además de OpenAI y xAI.
3. Generar los tres archivos de perfil con [06, sección 6](06-xai.md#6-preparar-el-perfil-xai-para-el-catálogo), [07, sección 7](07-openai-spiffe.md#7-preparar-el-perfil-openai-para-el-catálogo) y [08, sección 6](08-claude-spiffe.md#6-preparar-el-perfil-claude-para-el-catálogo). No repetir las secciones que crean apps, claves o roles.
4. Comprobar el [filtro SPIFFE de observabilidad](09-observabilidad.md#actualizar-el-filtro-spiffe-de-una-instalación-existente): debe incluir OpenAI y Claude. Actualizar solo ese dispositivo si conserva el filtro anterior.
5. Publicar el catálogo conjunto con el segundo bloque de la sección 1. Reiniciar solo Lumen con el código actualizado y el bloque de la sección 3; los forwards y ngrok siguen funcionando.
6. Comprobar la salud y probar los tres botones según la sección 6. Si falta una identidad, preparar antes su capítulo correspondiente.

La aplicación carga el catálogo al arrancar: cambiar modelos/IDs en Vault requiere reiniciar Lumen; cambiar entre perfiles ya cargados desde el banner no. La selección inicial se usa cuando el navegador todavía no tiene una preferencia guardada. El arranque sincroniza las claves públicas de Claude con el perfil administrativo descrito en [08](08-claude-spiffe.md).

**Cómo decide Vault:** al seleccionar una llamada a Vault, el botón pequeño junto al estado HTTP despliega su lógica y la auditoría correlacionada. Comprueba una lectura permitida y otra denegada: políticas, actor y RAR deben corresponder a la llamada seleccionada. Al cambiar de paso se cierra y descarta la evidencia anterior. [Datos disponibles y límites](../../chatbot/OBSERVABILITY.md#cómo-decide-vault).

**Consola de peticiones:** en cada paso de una traza nueva, **Abrir consola de peticiones** muestra la petición real editable (URL, método, cabeceras/token y cuerpo). Incluye mensajes, instrucciones y herramientas del LLM, los intercambios Verify/Vault y un editor SQL para MySQL. **Enviar petición real** ejecuta la llamada; también puedes copiar cURL o exportar a Postman. Los tokens no se renuevan y las capturas en memoria caducan a los diez minutos. [Uso, efectos y límites](../../chatbot/OBSERVABILITY.md#consola-para-repetir-una-llamada-real).
