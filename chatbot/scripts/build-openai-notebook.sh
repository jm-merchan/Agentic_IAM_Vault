#!/usr/bin/env bash
# Rebuild the reference notebook without outputs or credentials.
set -euo pipefail
cd "$(dirname "$0")/../.."
build=$(mktemp -d /tmp/lumen-openai-notebook.XXXXXX)
trap 'rm -rf "$build"' EXIT
printf '[]' > "$build/cells.json"
cell() {
  local kind=$1
  cat > "$build/source"
  jq --arg kind "$kind" --rawfile source "$build/source" '.+[{id:("openai-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$build/cells.json" > "$build/next"
  mv "$build/next" "$build/cells.json"
}
cell markdown <<'MD'
# OpenAI — Vault SPIFFE JWT-SVID y Workload Identity Federation

Referencia por etapas de la integración de Lumen con OpenAI. Usa **Bash, curl, jq y Vault CLI** para el aprovisionamiento; la aplicación y sus pruebas utilizan Python. Las celdas llaman a los mismos scripts de `demo.sh`; no es necesario ejecutarlas para arrancar la demo.

**Flujo:** Verify Client Credentials + RAR → Vault `verify/spiffe` → JWT-SVID → OpenAI token exchange → inferencia. El acceso a MySQL, Transit y Transform conserva el OBO del usuario. Vault emite la identidad SPIFFE; este laboratorio no instala SPIRE ni implementa su atestación de nodos/procesos.

[Configuración y capturas](docs/OPENAI_SPIFFE.md) · [Prueba de retirada/reinstalación](docs/E2E_OPENAI_VERIFICATION.md) · [README y prerrequisitos comunes](README.md).

Ejecutar desde la raíz del workspace con un kernel IPython que admita `%%bash`. Se entrega sin salidas ni credenciales.
MD
cell markdown <<'MD'
## 1. Prerrequisitos y `.env`

Completa primero los prerrequisitos del README: macOS/launchd, Podman o Docker activo, Minikube, kubectl, Helm 4, Vault CLI, jq, uv, licencia Vault con SPIFFE/Agentic IAM/Transform y las integraciones Verify, Tavily y Oracle/MySQL. Para OpenAI añade ngrok, un dominio de tu cuenta y una organización con acceso/cuota para el modelo.

| Entrada en `.env` | Uso |
|---|---|
| `OPENAI_ADMIN_API_KEY` | Aprovisionar proyecto/cuenta; se guarda también en `verify/secrets/openai-admin` |
| `LUMEN_MODEL_PROVIDER=auto` | Selección inicial OpenAI; el banner permite cambiar entre los tres perfiles cargados |
| `LUMEN_OPENAI_MODEL=gpt-4.1-nano` | Modelo de inferencia |
| `NGROK_DOMAIN=nondemanding-indistinguishably-claude.ngrok-free.dev` | Host HTTPS público del issuer, sin protocolo ni ruta |
| `NGROK_AUTHTOKEN` | Opcional si ngrok ya está autenticado en esta máquina |
| `SPIFFE_TRUST_DOMAIN=lumen.demo` | Dominio de confianza del SPIFFE ID |
| `OPENAI_PROJECT_ID`, `OPENAI_SERVICE_ACCOUNT_ID` | Los escribe `prepare-openai` |
| `OPENAI_IDENTITY_PROVIDER_ID` | ID del proveedor creado una vez en la UI OpenAI |

En OpenAI **Organization → Admin keys**, crear una clave **Restricted → Organization Administration: Write**, con las demás categorías en **None**. Guardarla directamente en `.env`, nunca en una celda. `.env` tiene permisos `600` y no se versiona. No rellenar un root token de Vault: el lanzador lo genera tras inicializarlo.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
export LUMEN_PROVIDER_OVERRIDE=openai LUMEN_PREPARE_OPENAI=1
bash scripts/demo/check.sh
CODE
cell markdown <<'MD'
## 2. Preparar Vault, issuer público y cuenta OpenAI

Esta celda también funciona antes de que Vault exista. Crea/inicializa Vault si falta, el namespace `verify`, el motor SPIFFE y los documentos públicos. La API administrativa crea o reutiliza `lumen-vault-demo` y `lumen-chatbot`; revoca la API key estática generada como efecto secundario al crear la cuenta. Conserva los IDs en `.env`.

| Script | Configuración |
|---|---|
| `scripts/demo/vault.sh` | Minikube, Vault TLS/Raft, init y unseal |
| `scripts/demo/bootstrap.sh` | Namespace y secretos estáticos de integración |
| `scripts/demo/spiffe.sh` | Motor, issuer, RS256, rol y TTL |
| `scripts/demo/ngrok.sh` | Publicación de discovery/JWKS y comprobación de rutas privadas |
| `scripts/demo/openai-admin.sh` | Proyecto/cuenta de servicio y revocación de la nueva clave estática |

El comando no crea la confianza WIF mediante endpoints privados del dashboard: esa parte se configura una vez en la UI oficial.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh prepare-openai
CODE
cell markdown <<'MD'
## 3. Inspeccionar la configuración SPIFFE

Motor `verify/spiffe`; rol `lumen-openai`; subject exacto `spiffe://lumen.demo/ns/verify/agent/lumen-openai`; audiencia `https://api.openai.com/v1`; TTL **300 segundos**. `jwt_oidc_compatibility_mode=true` añade los claims necesarios para la validación de OpenAI. `use_jti_claim=true` permite correlacionar emisiones; no convierte el JWT en un token de un solo uso.

El issuer es `https://<NGROK_DOMAIN>/v1/verify/spiffe`. Su URL y el trust domain SPIFFE son conceptos distintos. La clave de firma privada permanece en Vault.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
load_vault
export VAULT_NAMESPACE=verify
vault read -format=json spiffe/config | jq '.data'
vault read -format=json spiffe/role/lumen-openai | jq '.data'
CODE
cell markdown <<'MD'
## 4. Discovery/JWKS por ngrok

El servidor de archivos de ngrok publica solo documentos públicos de Vault. Un publicador Bash los actualiza cada 30 s y retira las copias si Vault deja de responder. No reenvía las peticiones externas a la API administrativa de Vault. Este diseño funciona con el dominio gratuito utilizado en el laboratorio, sin acciones de Traffic Policy de pago.

El arranque comprueba discovery, JWKS y HTTP 404 en rutas de secretos/administración. `stop` detiene el túnel y el publicador. Las cachés externas pueden conservar documentos públicos durante su TTL.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
curl -fsS --max-time 15 "https://$NGROK_DOMAIN/v1/verify/spiffe/.well-known/openid-configuration" | jq '{issuer,jwks_uri}'
curl -fsS --max-time 15 "https://$NGROK_DOMAIN/v1/verify/spiffe/.well-known/keys" | jq '{keys:[.keys[]|{kid,kty,alg,use}]}'
for path in /v1/sys/health /ui/ /v1/verify/spiffe/config /v1/verify/secrets/data/openai-admin; do
  status=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "https://$NGROK_DOMAIN$path")
  printf '%s → HTTP %s\n' "$path" "$status"
  [ "$status" = 404 ]
done
CODE
cell markdown <<'MD'
## 5. Crear el proveedor y mapping en OpenAI — una vez

En [Organization → Security → Workload Identity Provider](https://platform.openai.com/settings/organization/security/workload-identity-provider):

1. Crear `lumen-vault-spiffe`, tipo **OIDC**.
2. Issuer: el valor que imprime la celda siguiente. Audience: `https://api.openai.com/v1`.
3. Usar discovery normal: desmarcar custom discovery y uploaded JWKS. No añadir transformaciones CEL.
4. Crear mapping `lumen-chatbot`, **Key `sub`**, valor exacto del SPIFFE ID siguiente, sin wildcard.
5. Seleccionar el proyecto y la cuenta ya creados; desmarcar crear una nueva cuenta.
6. **Restricted → List models: Read; Model capabilities: Request**. Las demás categorías quedan en None. Corresponden a `api.model.read` y `api.model.request`; la UI muestra también el recuento de sus permisos internos.
7. Guardar el ID `idp_...` en `.env` como `OPENAI_IDENTITY_PROVIDER_ID`.

Si la confianza ya existe, comprobarla y reutilizarla. `remove` conserva estos recursos externos y sus IDs. Al recrear Vault, cambia el `kid`; el mismo issuer publica el nuevo JWKS.

[Captura histórica: Proveedor y mapping configurados](docs/runs/20261015-openai-spiffe/screenshots/openai-mapping-created.jpg)
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
jq -n '{issuer:("https://"+env.NGROK_DOMAIN+"/v1/verify/spiffe"),audience:"https://api.openai.com/v1",subject:("spiffe://"+(env.SPIFFE_TRUST_DOMAIN//"lumen.demo")+"/ns/verify/agent/lumen-openai"),project_id:env.OPENAI_PROJECT_ID,service_account_id:env.OPENAI_SERVICE_ACCOUNT_ID,identity_provider_id:env.OPENAI_IDENTITY_PROVIDER_ID}'
CODE
cell markdown <<'MD'
## 6. Arranque completo con OpenAI

Con los prerrequisitos externos completos, esta es la única orden necesaria. Configura MySQL/KMIP, Verify, tres perfiles, OBO, Transit/Transform, la identidad autónoma `chatbot-openai`, el banner y observabilidad. Reinicia Lumen para cargar el proveedor; conserva los datos y bloqueos ya existentes.

`chatbot/scripts/configure-openai.sh` configura la identidad del workload: Verify Client Credentials + RAR obligatorio y la política Vault que solo permite `update` sobre `spiffe/role/lumen-openai/mintjwt`, con la audiencia OpenAI obligatoria. La aplicación no recibe la Admin key. Su token bootstrap carga solo configuración/credenciales OAuth de ejecución y se revoca.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh start --provider openai
CODE
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
load_vault
export VAULT_NAMESPACE=verify
vault policy read chatbot-openai
vault kv get -format=json -mount=secrets chatbot/model | jq '.data.data|{provider,model,credential_source,credential_path,auth_flow,issuer,spiffe_id,audience,identity_provider_id,service_account_id}'
curl -fsS http://localhost:8088/health | jq .
CODE
cell markdown <<'MD'
## 7. Intercambio y vigencia

Por ejecución, [`app/spiffe.py`](chatbot/app/spiffe.py) realiza:

1. Verify `POST /oauth2/token`, Client Credentials con RAR exacto para `mintjwt`.
2. Vault `POST /v1/spiffe/role/lumen-openai/mintjwt`, namespace `verify`, body `{"audience":"https://api.openai.com/v1"}`. Obtiene `.data.token`.
3. Valida firma RS256, issuer, audiencia, subject y caducidad con JWKS público de Vault.
4. OpenAI `POST https://auth.openai.com/oauth/token`: grant `urn:ietf:params:oauth:grant-type:token-exchange`, subject type `urn:ietf:params:oauth:token-type:jwt`, JWT-SVID, provider ID y service account ID. No se envía la Admin key.
5. Usa el access token temporal como Bearer para la inferencia.

Cada ejecución que llama al modelo obtiene identidad y token nuevos; una continuación breve rechazada localmente por el control de ámbito no necesita llamar al modelo. OpenAI no devuelve refresh token; su access token no sobrevive al JWT-SVID. Se requieren más de 210 s restantes antes de empezar; ejecución máxima 180 s y margen 30 s. La siguiente consulta repite el intercambio. No hay fallback estático. La credencial SQL tiene su propio TTL de 120 s y flujo OBO.
MD
cell markdown <<'MD'
## 8. Verificación automática

Ejecutar cuando `start` haya terminado. Comprueba el runtime, las pruebas de aplicación, MySQL/privilegios/Tavily y el intercambio SPIFFE con inferencia real. La comprobación de OpenAI pide otra credencial y verifica que cambia. Genera un informe sin tokens ni claves.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh verify --provider openai
jq . chatbot/docs/openai-spiffe-verification.json
CODE
cell markdown <<'MD'
## 9. Recorrido de casos de uso

Lumen toma el idioma inicial del navegador y ofrece **EN / ES** arriba a la derecha. La elección guardada tiene prioridad y se aplica a la interfaz y siguientes respuestas de OpenAI, xAI o Claude. **Continue application**, **Save draft** y **View latest trace** corresponden a **Continuar solicitud**, **Guardar borrador** y **Ver última traza**. El cambio conserva conversación y formulario, y no modifica la federación ni los permisos. [Comprobaciones bilingües](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües).

Abrir **http://localhost:8088**, login Verify **Cloud Directory**. Consultar las credenciales en Vault `verify/secrets/chatbot/users/{reader,writer,supervisor}` fuera del notebook.

| Perfil/flujo | Comprobación |
|---|---|
| Lector | Preguntar por catálogo/inventario; los datos se consultan con SQL RO. Para catálogo, el servidor construye la respuesta tras una lectura OBO actual. Crear/revelar debe denegarse |
| Gestor | Preparar solicitud con el agente, completar cinco pasos con valores ficticios sugeridos y guardar. La fila contiene ciphertext/tokens; revelar se deniega |
| Supervisor | Consultar la fila enmascarada y revelar vía Transit + Transform. Crear/SQL RW sigue denegado |
| Todos | «Comprobar límites en Vault» valida nueve rutas reales y sus denegaciones esperadas |
| Tavily | «Una mirada más amplia»: agente registrado independiente → Vault → búsqueda pública |
| Bloqueos | `./demo.sh block database-read`, `database-write` o `decrypt`; repetir la acción y restaurar con `unblock` |

`block xai` controla únicamente el Secret Engine xAI; no bloquea OpenAI. Los bloqueos de datos son compartidos. El banner muestra el proveedor y el modelo elegido; el diagrama de trazas identifica la emisión SPIFFE o la credencial dinámica correspondiente.
MD
cell markdown <<'MD'
## 10. Trazas y auditoría

En el chat, **Ver última traza → Ver en Grafana**: `spiffe.mint_jwt_svid`, `verify.client_credentials`, `vault.write`, `openai.token_exchange`, `openai.chat`, herramientas y OBO. El control `guardrail.energy_scope` decide si la consulta pertenece a energía o a esta demo antes de ejecutar herramientas; una denegación no ejecuta el agente conversacional. [Control de ámbito y lectura del JWT-SVID](docs/ENERGY_SCOPE_AND_SVID.md). Los prompts/resultados se capturan mediante callbacks; no se captura razonamiento privado del modelo.

La configuración raw de este laboratorio conserva JWT de Verify y JWT-SVID en la respuesta de Vault. En `spiffe.mint_jwt_svid`, `spiffe.jwt_svid` muestra el token completo y `spiffe.jwt_svid.decoded` su cabecera/claims validados. En `openai.token_exchange`, `openai.exchange.subject_token` muestra el mismo token enviado a OpenAI. `lumen-spiffe-raw/` filtra solo la ruta de emisión en `verify`; se mantiene además la copia HMAC general. La Admin key no forma parte del runtime ni de esas trazas.

En el visor de Lumen, seleccionar la flecha y pulsar **Ver valores sensibles / View sensitive values** permite inspeccionar los valores de esa llamada. **EN / ES** traduce las etiquetas sin modificar JWT, secretos ni cuerpos HTTP. [Detalle del visor](chatbot/OBSERVABILITY.md#valores-de-cada-llamada).

La celda siguiente correlaciona la última prueba automática con Tempo/Loki. Para analizar una acción de la UI, sustituir `TRACE_ID` por el de esa acción. Las capturas y enlaces del [informe de reconstrucción](docs/E2E_OPENAI_VERIFICATION.md) identifican el despliegue probado.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
TRACE_ID=$(jq -er .trace_id chatbot/docs/openai-spiffe-verification.json)
LUMEN_OBSERVABILITY_REPORT=chatbot/docs/openai-observability-verification.json \
  bash chatbot/scripts/verify-observability.sh "$TRACE_ID"
CODE
cell markdown <<'MD'
## 11. Cambio de proveedor, limpieza y límites

Para cambiar entre proveedores ya cargados, usa los botones **OpenAI**, **xAI** y **Claude** del banner entre consultas; se conserva la conversación y no se repite OIDC. `./demo.sh start --provider openai`, `xai` o `anthropic` prepara las tres integraciones y fija la selección inicial cuando no hay preferencia guardada. Ese comando reinicia la aplicación y requiere volver a entrar. **EN / ES** es una preferencia independiente y no necesita reiniciar el proceso.

**Limpieza explícita, fuera de la ejecución rutinaria del notebook:** `./demo.sh remove --dry-run` muestra el alcance; `./demo.sh remove` elimina Vault, MySQL, observabilidad y recursos Lumen de Verify. Borra datos, claves de firma y trazas del cluster. Conserva `.env`, el cliente administrativo de Verify, los recursos OpenAI y el perfil Minikube. `./demo.sh start` reconstruye la demo. No se incluye una celda destructiva que se ejecute accidentalmente con «Run All».

El acceso inicial a Vault usa la identidad OAuth disponible en el laboratorio; no es atestación SPIRE. Un bloqueo de emisión no invalida por sí solo un access token de proveedor ya emitido. El mapping exacto, el TTL y, en Claude, la protección JTI acotan su uso. La configuración Claude está documentada en `docs/manual/08-claude-spiffe.md`.

Referencias: [OpenAI SPIFFE](https://developers.openai.com/api/docs/guides/workload-identity-federation/spiffe), [token exchange](https://developers.openai.com/api/reference/workload-identity-federation), [Vault SPIFFE](https://developer.hashicorp.com/vault/api-docs/secret/spiffe), [artículo HashiCorp](https://www.hashicorp.com/en/blog/implementing-workload-identity-with-hashicorp-vault-and-spiffe), [repo de referencia](https://github.com/DarthVaderRC/vault-spiffe).
MD
jq -n --slurpfile cells "$build/cells.json" '{nbformat:4,nbformat_minor:5,metadata:{kernelspec:{display_name:"Python 3 (IPython Bash magics)",language:"python",name:"python3"},language_info:{name:"python"}},cells:$cells[0]}' > 9_OpenAI_Vault_SPIFFE.ipynb
echo 'Notebook 9 generado, sin salidas ni credenciales.'
