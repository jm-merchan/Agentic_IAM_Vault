#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD_DIR=$(mktemp -d /tmp/lumen-notebook.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT
printf '[]' > "$BUILD_DIR/cells.json"
add_cell() {
  local kind=$1
  cat > "$BUILD_DIR/source"
  jq --arg kind "$kind" --rawfile source "$BUILD_DIR/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$BUILD_DIR/cells.json" > "$BUILD_DIR/next"
  mv "$BUILD_DIR/next" "$BUILD_DIR/cells.json"
}
add_cell markdown <<'MD'
# Lumen — chatbot con IBM Verify, Vault IAM y Deep Agents

Interfaz Python/NiceGUI y Deep Agents con selección OpenAI/xAI/Claude. Este notebook detalla la rama xAI (`grok-4.3`) y sus claves dinámicas de Vault; el [capítulo 10](docs/manual/10-aplicacion.md) prepara el catálogo conjunto de los tres proveedores. Mantiene OIDC Authorization Code + PKCE, MySQL mediante OBO y búsqueda Tavily con un agente autónomo registrado. **Todo el aprovisionamiento usa Bash, curl, jq y Vault CLI**; la aplicación y sus pruebas usan Python. Este notebook orquesta los archivos versionables de `chatbot/`, que deben acompañarlo.

La demo completa se instala con `./demo.sh`; este notebook es una referencia por etapas. Ejecutar desde la raíz del laboratorio. No copiar contraseñas en celdas. Las salidas del notebook se entregan vacías; los informes `chatbot/docs/*.json` registran las pruebas reales.

[Documentación y capturas](chatbot/README.md) · [Database Secrets Engine](3_Database_Secret_Engine.ipynb)
MD
add_cell markdown <<'MD'
## 1. Prerrequisitos

Vault Enterprise con Agentic IAM activo, namespace `verify`, `secrets/verify-admin` importado de `.env`, MySQL/KMIP y contexto Kubernetes `workshop`. `./demo.sh` prepara estos recursos y no depende del notebook 5. La configuración administrativa está en `${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/vault/config.env`; `/tmp/vault/config.env` es la ruta de compatibilidad. Necesarios: Bash, curl, jq, Vault CLI, kubectl, OpenSSL y uv.

El cliente administrativo de Verify necesita los permisos existentes y `manageUserStandardGroups`, `manageUsersPwdReset` para crear/activar los usuarios. No son permisos del agente en ejecución.

[Bootstrap administrativo histórico](verify/README.md) · [Historial y validación por alcance](docs/manual/VALIDACION.md).
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
for cmd in bash curl jq vault kubectl openssl uv; do command -v "$cmd"; done
bash verify/scripts/configure-base.sh
kubectl --context workshop -n mysql get pod mysql-enterprise-0
CODE
add_cell markdown <<'MD'
## 2. Instalar la aplicación

Entorno Python 3.12 aislado en `/tmp/vault-chatbot-venv`. Se puede recrear si macOS elimina `/tmp`; no modifica el `.venv` de los otros notebooks.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/install.sh
CODE
add_cell markdown <<'MD'
## 3. Roles de MySQL

Esta celda crea/actualiza tres planes ficticios y las tablas `energy_plans`, `service_requests` y `test_encryption` (con tres equipos ficticios si está vacía), cifradas con InnoDB TDE. Monta `database/` en **verify**, crea una conexión con administrador limitado a `scripting` y rota su contraseña. Roles `chatbot-readonly` (SELECT) y `chatbot-readwrite` (SELECT, INSERT, UPDATE, DELETE), TTL 120 s y máximo 300 s. No ejecuta la limpieza del notebook 3.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/01-database.sh
CODE
add_cell markdown <<'MD'
## 4. Aplicaciones OIDC, STS, usuarios, agentes y grupos

Se utiliza `verify/config/oidc-template.json`, una plantilla sin secretos ni ID de instancia y se crean recursos propios: `vault-chatbot-oidc`, `vault-chatbot-research`, `vault-chatbot-sts`. Sus secretos se guardan en Vault.

`lumen-reader` pertenece a `chatbot-readers`; `lumen-writer`, a `chatbot-writers`; `lumen-supervisor`, a `chatbot-supervisors`. Son usuarios locales Cloud Directory. Sus contraseñas están en `verify/secrets/chatbot/users/reader`, `writer` y `supervisor`. El script activa las cuentas por API sin enviar correos.

El último script asigna la aplicación a los tres grupos y sincroniza sus miembros con grupos internos de Vault. Ejecutarlo tras cambiar membresías; reiniciar la aplicación y volver a iniciar sesión. El script 06 prepara Transit, tokenización y la tabla adicional de solicitudes: requiere Transform en la licencia. Ver [notebook 8](8_Lumen_Protected_Applications.ipynb).
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/02-verify-apps.sh
bash chatbot/scripts/03-verify-users.sh
bash chatbot/scripts/06-data-protection.sh
bash chatbot/scripts/04-vault-agents.sh
bash chatbot/scripts/05-sync-groups.sh
CODE
add_cell markdown <<'MD'
## 5. Conectar el modelo y Tavily

En Vault, namespace `verify`, KV v2 `secrets`:

- `tavily`: campo `TAVILY_API_KEY` válido.
- `xai_mgmt`: management key utilizada por el plugin del [notebook 4](4_XAI_Secret_Engine.ipynb). El chatbot no puede leerla.

`./demo.sh` incluye `scripts/demo/xai.sh`: motor `verify/xai`, rol `lumen` con las ACL de chat/modelo como array JSON y caducidad nativa. `configure-xai.sh` crea un cliente Verify exclusivo de Client Credentials con RAR obligatorio y el agente registrado `chatbot-xai`, con permiso para `xai/creds/lumen` y el registro de autorización `secrets/data/chatbot/xai-access`. Su secreto OAuth se guarda en `secrets/chatbot/xai`; `chatbot/model` contiene configuración sin clave de inferencia. La clave estática `secrets/xai` queda fuera del flujo. Cada ejecución reautoriza la caché mediante una lectura real en Vault. `./demo.sh block xai` instala un deny y revoca sus leases; `unblock` restaura el acceso. También existen los controles `database-read`, `database-write` y `decrypt`; véase `docs/ACCESS_BLOCKS.md`.

```bash
bash chatbot/scripts/configure-xai.sh
```

La aplicación reutiliza la clave dinámica en memoria mientras queden más de 210 s. Cuando no cubre el presupuesto de ejecución (180 s) y el margen (30 s), solicita otra de 300 s. El plugin no implementa renovación: se obtiene una clave nueva, sin extender artificialmente la vigencia de la anterior. Un lock evita emisiones simultáneas duplicadas. Client Credentials identifica al workload de inferencia; OBO sigue aplicando el permiso humano en MySQL y datos sensibles. El aprovisionamiento conserva el rol existente; crea uno con valores iniciales solo si falta. La clave xAI dinámica se incluye en la respuesta de Vault capturada en modo raw, según la configuración de este laboratorio.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
source verify/scripts/common.sh
bash chatbot/scripts/configure-xai.sh
for name in tavily chatbot/xai chatbot/model; do
  if vault kv metadata get -mount=secrets "$name" >/dev/null 2>&1; then
    printf '%s: existe\n' "$name"
  else
    printf '%s: pendiente\n' "$name"
  fi
done
CODE
add_cell markdown <<'MD'
### Verificar inferencia, aislamiento y caducidad

Esta comprobación crea una clave de prueba de 60 s, invoca Grok, comprueba las denegaciones del agente y del bootstrap y espera a su caducidad. Puede tardar unos dos minutos. Solo imprime resultados, nunca claves ni JWT.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/verify-xai.sh
jq '{all_passed,expired_xai_http_status,tests}' chatbot/docs/xai-dynamic-verification.json
CODE
add_cell markdown <<'MD'
## 6. Iniciar Lumen

La siguiente celda permanece ejecutándose. Abrir **http://localhost:8088** en Chrome; usar exactamente `localhost` por el callback OIDC. Elegir Cloud Directory y uno de los usuarios de prueba. La contraseña puede consultarse en la UI de Vault.

**Idioma:** Lumen detecta el idioma del navegador y ofrece **EN / ES** arriba a la derecha. La elección guardada prevalece, se conserva al volver a entrar y afecta al chat, formularios, trazas y siguientes respuestas. El historial y los valores capturados permanecen originales. No requiere variables de `.env` ni cambios de identidades. [Uso y mantenimiento](chatbot/README.md#idioma-español-e-inglés).

El servidor escucha solo en loopback; abre el port-forward MySQL 13306. Carga las credenciales con un token Vault de bootstrap de cinco minutos y lo revoca inmediatamente. El proceso Python no recibe el token raíz.

`CHATBOT_VERIFY_ACCESS=1` ejecuta pruebas reales OBO al completar cada login y escribe informes sin tokens. Las inserciones de estas pruebas se revierten; las credenciales expiran en 120 s. Quitar la variable para una ejecución normal.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
CHATBOT_VERIFY_ACCESS=1 bash chatbot/scripts/run.sh
CODE
add_cell markdown <<'MD'
## 7. Probar los dos flujos

1. Entrar como `lumen-reader`: consultar planes; intentar preparar una solicitud. Vault deniega incluso un token OBO que solicite el rol RW.
2. Cambiar a `lumen-writer` (gestor): completar cinco pasos, revisar y guardar. Consultar «Solicitudes», siempre enmascaradas. Intentar revelar: Vault devuelve 403. Cambiar a `lumen-supervisor`: puede revelar pero no crear ni obtener SQL RW. Recorrido completo en el notebook 8.
3. «Una mirada más amplia» usa la identidad autónoma `chatbot-research`: Client Credentials → Agent Registry → secreto Tavily → búsqueda. No usa el token humano para obtener Tavily.
4. Con modelo configurado: pedir «Consulta las tarifas de electricidad del catálogo de Lumen». El servidor construye la respuesta del catálogo a partir de una lectura OBO actual. Realizar la búsqueda pública en otra consulta para revisar sus fuentes y llamadas Tavily.
5. Alternar modo claro/oscuro y comprobar móvil. Probar también **EN / ES** siguiendo la [comprobación bilingüe](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües): detección inicial, elección persistente, respuestas en el idioma elegido y conservación del formulario. En inglés, **Applications**, **Continue application** y **Use test data** equivalen a **Solicitudes**, **Continuar solicitud** y **Usar datos de prueba**.

![Catálogo con solo lectura](docs/runs/20261014T162141Z/screenshots/03-reader-agent.jpg)

![Modo oscuro](docs/runs/20261014T162141Z/screenshots/16-form-mobile-dark.jpg)

Las políticas autorizan **roles SQL por base de datos**, no filas. Los borradores originales filtran por `subject_id`; la nueva bandeja de laboratorio es compartida y enmascarada. Los permisos de descifrado/tokenización son independientes de SQL. Vault no transforma automáticamente el claim groups en políticas: el script 05 sincroniza identidades.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
# Ejecutar con el servidor/port-forward activo en otra celda o terminal.
bash chatbot/scripts/test-infrastructure.sh
cd chatbot
/tmp/vault-chatbot-venv/bin/python -m pytest -q tests
for report in docs/obo-readonly.json docs/obo-readwrite.json docs/obo-supervisor.json; do
  if [ -f "$report" ]; then jq '{role,all_passed,tests}' "$report"; else echo "Pendiente: $report"; fi
done
CODE
add_cell markdown <<'MD'
## 8. Detener y límites del laboratorio

Interrumpir la celda/terminal del servidor. El port-forward que abrió se cierra y las credenciales dinámicas caducan. Se conservan usuarios, apps, agentes, grupos y datos para repetir la demo. No se incluye una limpieza destructiva automática.

Sesiones OIDC de 10 minutos, memoria local, un único proceso. Para exponer fuera de localhost hacen falta HTTPS, cookie Secure, almacenamiento compartido de sesiones, límites de uso, gestión de secretos de workload y sincronización continua de grupos. No reutilizar el token de bootstrap como identidad del agente.
MD
jq -n --slurpfile cells "$BUILD_DIR/cells.json" '{nbformat:4,nbformat_minor:5,metadata:{kernelspec:{display_name:"Python 3 (IPython Bash magics)",language:"python",name:"python3"},language_info:{name:"python"}},cells:$cells[0]}' > 6_Lumen_Chatbot_Vault_IAM.ipynb
printf 'Notebook 6 generated.\n'
