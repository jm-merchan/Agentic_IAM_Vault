#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build_dir=$(mktemp -d /tmp/verify-notebook.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT
printf '[]' > "$build_dir/cells.json"
add_cell() {
  local kind=$1
  cat > "$build_dir/source"
  jq --arg kind "$kind" --rawfile source "$build_dir/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$build_dir/cells.json" > "$build_dir/next"
  mv "$build_dir/next" "$build_dir/cells.json"
}
add_cell markdown <<'MD'
# IBM Verify + Vault Agentic IAM y OBO — Bash / API

Este notebook conserva el ejercicio base `verify-agent`; Lumen completo se inicia con `./demo.sh` y no requiere su sesión humana guardada. Este ejercicio configura el laboratorio existente `merchan.verify.ibm.com` y Vault `https://127.0.0.1:8443`, **exclusivamente en el namespace `verify`**. Todas las celdas de código usan Bash (`%%bash`); el kernel IPython solamente ejecuta esa magic. No hay scripts Python.

El cliente administrativo se creó una vez en la UI porque todavía no había credenciales API administrativas. El resto se configura con `curl`, `jq` y la CLI de Vault. Se reutiliza `vault-authn-entry`; no se recrea ni se regenera su secreto.

## Estado comprobado

Configuración aplicada y scripts ejecutados contra el tenant y Vault. Las pruebas autónomas y OBO se recogen al final. Las celdas no incluyen tokens ni contraseñas, y sus salidas se entregan limpias. El informe de ejecución es independiente de los contadores de Jupyter.

El humano se autentica con Authorization Code + PKCE; el actor usa Client Credentials de `vault-authn-entry`. El STS intercambia ambos tokens y agrega RAR. Vault valida el JWT en cada petición, sin crear un token Vault intermedio.
MD
add_cell markdown <<'MD'
## 1. Prerrequisitos y bootstrap

Abrir el notebook con el kernel `.venv`/Python 3 del proyecto. Ejecutar desde la raíz del proyecto o desde `verify/`. Se requieren Bash 3.2+, `curl`, `jq`, `vault`, `openssl` y `nc` (callback local en macOS). Vault debe estar accesible y desbloqueado; `/tmp/vault/config.env` contiene `VAULT_ADDR`, `VAULT_TOKEN` y `VAULT_CACERT`.

Ya existen en el namespace `verify`, motor KV v2 `secrets/`:

| Ruta | Uso |
|---|---|
| `verify` | Cliente OAuth de la aplicación, con `client_id` y `client_secret` |
| `verify-admin` | Cliente `vault-verify-automation`, con `client_id`, `client_secret` y `tenant` |

Para otro tenant hay que adaptar explícitamente el código y crear el bootstrap en **Seguridad → Acceso de API**. Permisos: `manageAppAccessAdmin`, `manageSTSClients`, `manageAuthDetailTypes` y `readUsers`. El último comprueba el sujeto en el directorio. Guardar la credencial en Vault; no introducirla en una celda ni en sus salidas.

![Cliente API con cuatro permisos](docs/screenshots/09-api-automation-client.jpg)
MD
add_cell markdown <<'MD'
## 2. Scripts compartidos

Los scripts del workspace son la fuente de implementación. Este notebook no los sobrescribe con copias embebidas, para evitar recuperar versiones antiguas después de una revisión.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify ]; then cd verify; fi
for file in scripts/0*.sh scripts/common.sh scripts/configure-base.sh; do bash -n "$file"; done
CODE
add_cell markdown <<'MD'
## 3. Verificar conectividad e inventario

Esta etapa no cambia recursos. Comprueba la CA de Vault, el namespace, el motor KV, las credenciales y las APIs administrativas. El inventario imprime solo identificadores y nombres de recursos.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/00-preflight.sh
bash scripts/01-inventory.sh
CODE
add_cell markdown <<'MD'
## 4. Configurar Verify por API

Se localiza la aplicación existente por nombre y se actualiza preservando su configuración y credencial. Se establece JWT, Code/query, cliente confidencial con Basic, PKCE y `may_act.client_id`.

Se crea `vault:path_access` con un esquema de ruta/capacidades y se comprueba su contenido. El texto de consentimiento debe enviarse codificado en base64: es un requisito de la API de Verify. Se crea o actualiza `vault-obo-sts`, que exige token de actor, emite JWT de 600 segundos y no recibe permisos administrativos de Verify.

La introspección STS usa `name` (no `targetName`) y la regla personalizada `{"sub":requestContext["actor_token"].sub}` para `actor-token`. La API rechaza `sourceId` cuando se usa una regla personalizada.

La credencial STS se guarda en `secrets/verify-sts`; los IDs de recursos, en `secrets/verify-config`. La reejecución reutiliza la aplicación, el tipo RAR y el STS existentes.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/02-configure-verify.sh
CODE
add_cell markdown <<'MD'
![STS creado por API](docs/screenshots/10-sts-created-api.jpg)

![Tipo RAR creado por API](docs/screenshots/11-rar-created-api.jpg)

## 5. Obtener un token humano con PKCE

Esta celda muestra una URL de autorización y espera hasta diez minutos. Abrirla en Chrome y completar IBMid y el consentimiento. Si IBMid lleva primero al dashboard, abrir de nuevo la misma URL mientras la celda sigue esperando. El callback usa `http://localhost:9876/callback` y `nc` escucha únicamente en `127.0.0.1`.

La celda comprueba `state`, intercambia el código con el verificador PKCE, comprueba issuer, caducidad y `may_act`, y guarda el resultado en `secrets/verify-human-session`. Nunca imprime JWT. El decodificado local no verifica la firma: Vault lo hace al probar el acceso.

Si hay otro proceso escuchando en 9876, cerrarlo antes. No lanzar dos ejecuciones simultáneas de esta etapa. La credencial humana caduca: repetir esta celda cuando sea necesario.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/03-human-login.sh
CODE
add_cell markdown <<'MD'
## 6. Configurar Vault en verify

Se crean o actualizan el perfil OAuth `verify`, las entidades `verify-human` y `verify-agent`, sus aliases y las políticas. Se comprueba el ID humano contra el directorio de Verify y se usa el `sub` del token Client Credentials para el agente.

**Ajuste necesario verificado en este laboratorio:** `actor_claim="actor-token.sub"`. El valor predeterminado `act.sub` no identifica al actor de estos JWT, cuyo `act` contiene `client_id`. La ruta RAR es `secrets/data/agentic-demo/shared`, relativa al namespace; no lleva el prefijo `verify/`.

Siguiendo la limitación de STS descrita por HashiCorp, este perfil no configura `audiences`; valida issuer, JWKS, RS256 y las identidades registradas. El perfil exige RAR; únicamente el registro de este agente tiene `optional_authorization_details=true` para permitir su flujo autónomo Client Credentials. Cuando se incluye RAR, sigue siendo restrictivo.

El agente solo puede leer `shared`. El humano tiene lectura de `shared` y `human-only`. La delegación debe respetar la intersección entre la política humana, el límite del agente y RAR. Ninguna política de demo permite leer credenciales de bootstrap.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/04-configure-vault.sh
CODE
add_cell markdown <<'MD'
![Agente registrado en verify](docs/screenshots/12-vault-agent-registry.jpg)

## 7. Token Exchange y pruebas de autorización

Se obtiene un token nuevo del actor, se intercambia con el humano en el STS y se valida la estructura de las claims. El token delegado queda en `secrets/verify-delegated-session`. Las peticiones directas a Vault usan el JWT y `X-Vault-Namespace: verify`.

Se prueban accesos positivos y negativos. Dos pruebas adicionales aíslan el límite del agente y RAR, de modo que un HTTP 403 no se interprete simplemente como evidencia de que el JWT funciona. La lectura positiva acredita que Vault ha aceptado la firma e identidades.

El informe público `docs/api-verification.json` contiene solo fecha, resultados y estados HTTP. Si alguna comprobación falla, el script termina con error y no sustituye el informe exitoso anterior; comprobar siempre su fecha.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/05-test-access.sh
jq . docs/api-verification.json
CODE
add_cell markdown <<'MD'
## 8. Repetir la demostración

Para otra demostración, ejecutar la etapa 5 para renovar el token humano y la 7 para generar un token delegado nuevo y probar el acceso. Las etapas de configuración pueden repetirse sin duplicar los recursos del laboratorio; actualizan los objetos gestionados por estos scripts. El motor KV mantiene versiones de las credenciales y sesiones.

Este notebook parte del tenant y la aplicación existentes. No crea una cuenta IBM Verify, no modifica el despliegue Minikube ni toca el material archivado de Okta. ROPC quedó habilitado en la preparación inicial del laboratorio, pero estos scripts no lo utilizan.

Referencias:

- [HashiCorp: IBM Verify](https://developer.hashicorp.com/vault/ai/iam/providers/verify)
- [HashiCorp: OBO](https://developer.hashicorp.com/vault/ai/iam/setup-obo)
- [HashiCorp: perfil OAuth y actor_claim](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server)
- [HashiCorp: RAR opcional](https://developer.hashicorp.com/vault/ai/iam/make-rar-optional)
- [IBM: API de aplicaciones](https://docs.verify.ibm.com/verify/reference/updateapplication)
- [IBM: API STS](https://docs.verify.ibm.com/verify/reference/createstsclient)
- [IBM: API de tipos RAR](https://docs.verify.ibm.com/verify/reference/createauthdetailtype)
MD
jq -n --slurpfile cells "$build_dir/cells.json" '{cells:($cells[0]|to_entries|map(.value+{id:("verify-cell-"+(.key|tostring))})),metadata:{kernelspec:{display_name:"Python 3 (celdas Bash)",language:"python",name:"python3"},language_info:{name:"python"}},nbformat:4,nbformat_minor:5}' > 5_IBM_Verify_Vault_Agentic_IAM_Bash.ipynb
printf 'Notebook generado: verify/5_IBM_Verify_Vault_Agentic_IAM_Bash.ipynb\n'
