#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
build_dir=$(mktemp -d /tmp/lumen-oauth2c-notebook.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT
printf '[]' > "$build_dir/cells.json"
add_cell() {
  local kind=$1 id=$2
  cat > "$build_dir/source"
  jq --arg kind "$kind" --arg id "$id" --rawfile source "$build_dir/source" \
    '.+[{id:$id,cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+
    (if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' \
    "$build_dir/cells.json" > "$build_dir/next"
  mv "$build_dir/next" "$build_dir/cells.json"
}
add_cell markdown introduction <<'MD'
# 10 · Obtener tokens con oauth2c: IBM Verify y Vault

Ejemplos ejecutables para **Lumen ya instalado**. `oauth2c` solicita los tokens; **IBM Verify los emite**. Vault acepta el JWT delegado directamente para autorizar la operación, sin intercambiarlo por otro token Vault.

El recorrido adapta la [validación de tokens de HashiCorp](https://developer.hashicorp.com/vault/ai/iam/providers/verify#step-8-validate-token-retrieval) y su [intercambio OBO](https://developer.hashicorp.com/vault/ai/iam/providers/verify#step-9-validate-token-exchange) a los clientes reales del repositorio. La URL antigua `#step-9-validate-token-retrieval` corresponde ahora al paso 8.

| Ejemplo | Cliente que se autentica | Token obtenido | Uso |
|---|---|---|---|
| Client Credentials | `vault-chatbot-oidc` | Actor del agente | Entrada `actor_token` del intercambio |
| Authorization Code + PKCE | `vault-chatbot-oidc` + persona en el navegador | Usuario humano | Entrada `subject_token` del intercambio |
| Token Exchange + RAR | `vault-chatbot-sts` | Delegado OBO | Lectura de `database/creds/chatbot-readonly` |
| Client Credentials autónomo | `vault-chatbot-research` | Agente research | Identidad sin usuario; RAR opcional en su registro Vault |
| Refresh Token, condicional | Cliente OIDC | Nuevo access token | Solo si la respuesta humana contiene refresh token |

Lumen desactiva **ROPC** y **refresh tokens**. Este notebook conserva esa configuración: el último ejemplo explica y detecta el caso no disponible.

## Quién llama a quién

```text
oauth2c ── Client Credentials, Basic OIDC ───────────────> Verify /oauth2/token
        <────────────────────────────────────────────── actor token

navegador ── login + consentimiento + PKCE ─────────────> Verify /oauth2/authorize
          <── código en http://localhost:9876/callback ──┘
oauth2c ── código + verifier + Basic OIDC ──────────────> Verify /oauth2/token
        <────────────────────────────────────────────── human access token

oauth2c ── human + actor + RAR + Basic STS ─────────────> Verify /oauth2/token
        <────────────────────────────────────────────── delegated access token

Vault CLI ── delegated JWT + namespace verify ─────────> Vault /v1/database/creds/chatbot-readonly
          <──────────────────────────────────────────── credencial MySQL temporal
```

El STS es un cliente distinto del actor, aunque ambos usen el mismo endpoint. La credencial Basic identifica al **cliente que solicita el intercambio**; `actor_token` identifica al **agente que actuará**.
MD
add_cell markdown prerequisites <<'MD'
## 1. Preparación

Abre este archivo desde la raíz del repositorio con el kernel Python/IPython local (`.venv`, IPython 9). Las celdas `%%bash` muestran la URL de login mientras esperan. Ejecuta una celda cada vez; el navegador y el kernel deben estar en el mismo Mac.

Necesitas el laboratorio preparado mediante `./demo.sh` o el [manual](docs/manual/README.md), con Vault desbloqueado, MySQL activo y los usuarios/grupos sincronizados. No se reconstruye la demo.

Dependencias: Bash 3.2+, Vault CLI, curl, jq, OpenSSL, Python 3 y **oauth2c 1.21.1**, versión comprobada para estos ejemplos. Si falta oauth2c, instala desde una terminal con `brew install cloudentity/tap/oauth2c` ([fuente oficial](https://github.com/SecureAuthCorp/oauth2c#installation)).

Cada celda carga de nuevo `.env` y `$LUMEN_STATE_DIR/vault/config.env`; no depende de variables creadas por otra celda ni de `manual/session.sh`. La ruta de estado predeterminada es `~/.local/state/lumen-vault-demo`. Los resultados se guardan en su subdirectorio **`oauth2c/`**, con permisos privados; no se guardan tokens en el repositorio ni en KV.

El [helper compartido](verify/scripts/oauth2c-common.sh) carga el entorno, prepara archivos de cliente y comprueba caducidad. Los comandos que solicitan los tokens quedan visibles en las celdas.

| Credencial existente en Vault, namespace `verify`, KV v2 `secrets` | Finalidad |
|---|---|
| `chatbot/oidc` | Login de la persona y token del actor |
| `chatbot/sts` | Token exchange |
| `chatbot/research` | Ejemplo autónomo |
| `verify-admin` | Añadir y retirar exclusivamente el callback temporal |

`lab_credential` lee de Vault `CLIENT_ID` y `CLIENT_SECRET` para la celda actual. Los valores se pasan a las opciones de oauth2c y quedan también en un archivo privado para inspección; no se pegan literales en el notebook. Como en los ejemplos de la herramienta, secretos y tokens pasan por argumentos del proceso local. `--silent` produce JSON por stdout; `--no-browser` muestra la URL de login por stderr. Los scopes se separan con **comas** en la CLI.
MD
add_cell code preflight <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
oauth2c version
help_text=$(oauth2c --help)
for flag in --callback-addr --rar --actor-token --requested-token-type; do
  case "$help_text" in *"$flag"*) ;; *) lab_fail "La versión instalada no admite $flag." ;; esac
done
for name in oidc sts research; do lab_credential "$name" "chatbot/$name"; done
printf 'Issuer: %s\nNamespace Vault: verify\nArchivos privados: %s\n' "$ISSUER" "$LAB"
printf 'Credenciales OIDC, STS y research disponibles.\n'
CODE
add_cell markdown actor-description <<'MD'
## 2. Ejemplo A: token del agente con Client Credentials

No abre un navegador. El resultado representa a `chatbot-oidc`, no a una persona. Por sí solo no completa la delegación: el registro de este agente en Vault exige RAR.

La respuesta completa queda en `actor.json`; se muestran las claims y la duración. Repetir esta celda renueva el actor y descarta el token OBO anterior para evitar mezclar ejecuciones.
MD
add_cell code actor <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/actor.json" "$LAB/obo.json"
lab_credential oidc chatbot/oidc
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type client_credentials \
  --auth-method client_secret_basic \
  --scopes openid,profile,email \
  --silent > "$WORK/actor.json"
lab_save_token actor "$WORK/actor.json"
CODE
add_cell markdown callback-description <<'MD'
## 3. Preparar el callback del login humano

Esta celda **añade `http://localhost:9876/callback` a `vault-chatbot-oidc` en Verify**. Mantiene `http://localhost:8088/auth/callback` y el resto de su configuración. Obtiene un token administrativo nuevo con oauth2c; no depende de `verify.headers` ni de un token administrativo anterior.

Guarda si el callback ya existía. La limpieza solo lo retira si este notebook lo añadió; no restaura una copia antigua de la aplicación. No ejecutes a la vez una reconfiguración de aplicaciones ni otra sesión de este notebook. No cambia grants, contraseñas, grupos, políticas ni secretos de cliente.
MD
add_cell code callback-add <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_port_free
lab_callback add
CODE
add_cell markdown human-description <<'MD'
## 4. Ejemplo B: token humano con Authorization Code + PKCE

Ejecuta la celda, abre la URL que aparece en su salida y entra con **`lumen-reader`**. Comprueba la cuenta seleccionada si Verify conserva otra sesión. Acepta el consentimiento y deja que vuelva al callback. La celda espera hasta cinco minutos; no ejecutes la siguiente hasta que termine.

`--pkce` añade el desafío S256 y envía el verifier al canjear el código. `oauth2c` escucha solo en `127.0.0.1:9876`, separado del puerto 8088 de Lumen. No hace falta detener Lumen.

El resultado esperado contiene `sub` humano, `groups` y `may_act.client_id` igual al cliente OIDC. Para OBO se usa **`access_token`**, no `id_token`. Decodificar un JWT permite inspeccionarlo; no prueba su firma ni sus permisos. La lectura posterior contra Vault verifica la aceptación efectiva del token delegado.
MD
add_cell code human <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/human.json" "$LAB/obo.json"
lab_port_free
lab_credential oidc chatbot/oidc
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type authorization_code \
  --auth-method client_secret_basic \
  --response-types code --response-mode query \
  --scopes openid,profile,email \
  --pkce --redirect-url "$CALLBACK" --callback-addr 127.0.0.1:9876 \
  --browser-timeout 5m --no-browser --silent > "$WORK/human.json"
client_id=$(jq -er .client_id "$LAB/oidc-client.json")
lab_claims "$WORK/human.json" | jq -e --arg cid "$client_id" \
  '.may_act.client_id==$cid and (.groups|type=="array" and length>0)' >/dev/null ||
  lab_fail 'Falta may_act o groups; revisa el cliente OIDC y el grupo del usuario.'
lab_save_token human "$WORK/human.json"
CODE
add_cell markdown exchange-description <<'MD'
## 5. Ejemplo C: token delegado con Token Exchange y RAR

Se utiliza **la credencial STS**, el token humano y el del actor. `--rar` transmite `authorization_details`; la ruta es relativa al namespace Vault: **`database/creds/chatbot-readonly`**, sin `verify/` ni `/v1/`.

El RAR pide capacidad **`read`**, aunque la operación genere una credencial dinámica. Vault combina los permisos del humano, el techo del agente y el RAR. Que Verify emita el token no garantiza que Vault permita todas las rutas solicitadas.

En Lumen, el perfil OAuth de Vault usa **`actor_claim=actor-token.sub`**; no debe confundirse con `act.client_id`. Se comprueba la relación entre `sub`, `actor-token.sub` y las claims originales.

Los tokens duran aproximadamente diez minutos con la configuración del instalador. Si has tardado demasiado en el login, repite A y luego C; si caducó el humano, repite B y C.
MD
add_cell code exchange <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/obo.json"
lab_require_token human
lab_require_token actor
lab_credential sts chatbot/sts
RAR=$(jq -cn '[{type:"vault:path_access",path:"database/creds/chatbot-readonly",capabilities:["read"]}]')
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type urn:ietf:params:oauth:grant-type:token-exchange \
  --auth-method client_secret_basic \
  --subject-token "$(jq -er .access_token "$LAB/human.json")" \
  --subject-token-type urn:ietf:params:oauth:token-type:access_token \
  --actor-token "$(jq -er .access_token "$LAB/actor.json")" \
  --actor-token-type urn:ietf:params:oauth:token-type:access_token \
  --requested-token-type urn:ietf:params:oauth:token-type:access_token \
  --rar "$RAR" --silent > "$WORK/obo.json"
lab_claims "$WORK/obo.json" | jq -e \
  --arg subject "$(lab_claims "$LAB/human.json" | jq -er .sub)" \
  --arg actor "$(lab_claims "$LAB/actor.json" | jq -er .sub)" \
  --argjson rar "$RAR" \
  '.sub==$subject and .["actor-token"].sub==$actor and .authorization_details==$rar' >/dev/null ||
  lab_fail 'El JWT delegado no conserva el sujeto, actor o RAR esperados.'
lab_save_token obo "$WORK/obo.json"
CODE
add_cell markdown vault-description <<'MD'
## 6. Usar el token delegado contra Vault

La siguiente lectura **emite una credencial MySQL temporal**. No ejecuta SQL ni modifica solicitudes de energía. La sustitución de `VAULT_TOKEN` afecta solo a ese comando; la credencial administrativa cargada para leer el bootstrap no se utiliza para probar el acceso.

Resultado esperado: credencial RO para lector, gestor y supervisor, si los bloqueos adicionales de la demo están desactivados. Guarda `database.json` para inspeccionar usuario, contraseña y lease.
MD
add_cell code vault-positive <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_require_token obo
rm -f "$LAB/database.json"
VAULT_TOKEN=$(jq -er .access_token "$LAB/obo.json") \
  vault read -format=json database/creds/chatbot-readonly > "$WORK/database.json"
jq -e '.data.username|type=="string" and length>0' "$WORK/database.json" >/dev/null
mv "$WORK/database.json" "$LAB/database.json"
jq '{lease_id,lease_duration,renewable,username:.data.username}' "$LAB/database.json"
CODE
add_cell markdown negative-description <<'MD'
### Comprobar una denegación con el mismo JWT

El mismo token limitado a RO no permite pedir `database/creds/chatbot-readwrite`. La celda exige **HTTP 403 / permission denied**: un fallo de TLS, timeout o token caducado no cuenta como prueba correcta. Esta denegación es compatible con el límite RAR; usando `lumen-reader`, su política humana también deniega RW. Para aislar RAR, repite el login como `lumen-writer` y comprueba su permiso RW por separado en el [capítulo 11](docs/manual/11-obo.md).
MD
add_cell code vault-negative <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_require_token obo
if VAULT_TOKEN=$(jq -er .access_token "$LAB/obo.json") \
  vault read -format=json database/creds/chatbot-readwrite \
  > "$WORK/unexpected.json" 2> "$WORK/denied.log"; then
  lab_fail 'Vault permitió RW con un RAR limitado a RO; revisa perfil y políticas.'
fi
if grep -Eq 'Code: 403|Code:403' "$WORK/denied.log" &&
   grep -qi 'permission denied' "$WORK/denied.log"; then
  printf 'OK: Vault ha denegado la ruta RW con HTTP 403.\n'
else
  lab_fail 'El fallo no fue la denegación 403 esperada. Comprueba conectividad y caducidad.'
fi
CODE
add_cell markdown autonomous-description <<'MD'
## 7. Ejemplo D: agente autónomo research

No requiere login humano ni STS. Emite un token con el cliente `vault-chatbot-research`. Su registro Vault tiene `optional_authorization_details=true` y una política limitada a `secrets/data/tavily`; esto permite su uso autónomo sin RAR. No convierte al actor OIDC en un agente sin restricciones.

Esta celda solo obtiene el token e inspecciona sus claims; no llama a Tavily ni lee su API key.
MD
add_cell code autonomous <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/research.json"
lab_credential research chatbot/research
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type client_credentials \
  --auth-method client_secret_basic \
  --scopes openid,profile,email \
  --silent > "$WORK/research.json"
lab_save_token research "$WORK/research.json"
CODE
add_cell markdown refresh-description <<'MD'
## 8. Ejemplo E: refresh token, solo si existe

El instalador de Lumen fija `generateRefreshToken=false`. La celda indicará **«omitido»** con la configuración actual y no cambiará Verify para habilitarlo. Se incluye el comando completo para una configuración que sí emita `refresh_token`.

Un refresh token es una credencial diferente del access token: no se puede sustituir uno por otro. La respuesta renovada se guarda aparte en `refreshed.json`; el flujo OBO de este notebook sigue tomando `human.json`.
MD
add_cell code refresh <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/refreshed.json"
[ -f "$LAB/human.json" ] || lab_fail 'Ejecuta primero el login humano.'
if jq -e '.refresh_token|type=="string" and length>0' "$LAB/human.json" >/dev/null; then
  lab_credential oidc chatbot/oidc
  oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
    --grant-type refresh_token \
    --auth-method client_secret_basic \
    --refresh-token "$(jq -er .refresh_token "$LAB/human.json")" \
    --silent > "$WORK/refreshed.json"
  lab_save_token refreshed "$WORK/refreshed.json"
else
  printf 'Refresh omitido: la respuesta humana no contiene refresh_token; Lumen lo desactiva.\n'
fi
CODE
add_cell markdown inspect-description <<'MD'
## 9. Ver los valores completos

Esta celda imprime las respuestas OAuth completas —JWT, ID token y refresh token si existe— y las credenciales dinámicas obtenidas. Los valores no se sustituyen por asteriscos. Las salidas quedan en el notebook si lo guardas después; el archivo entregado está limpio.

El secreto Basic está en `*-client.json`. Puedes inspeccionar, por ejemplo, `jq . "$LAB/oidc-client.json"` dentro de una celda que cargue el helper. El JSON de configuración no es un token.
MD
add_cell code inspect <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
for name in actor human obo research refreshed database; do
  if [ -f "$LAB/$name.json" ]; then
    printf '\n=== %s ===\n' "$name"
    jq . "$LAB/$name.json"
  fi
done
CODE
add_cell markdown cleanup-description <<'MD'
## 10. Retirar el callback temporal

Ejecuta esta celda también si interrumpiste el recorrido tras preparar el callback. Solo retira la URI 9876 si este notebook la añadió, y conserva los demás callbacks actuales. Mantiene los archivos privados para poder inspeccionarlos después.

Los JWT caducan según `exp`; quitar el callback **no los revoca**. Las credenciales MySQL siguen la duración de su lease. Para retirarlas antes, el comando administrativo sería `vault lease revoke "$(jq -er .lease_id "$LAB/database.json")"` tras cargar el helper; no se ejecuta automáticamente.

Cuando ya no necesites las capturas, elimina únicamente los JSON de este ejercicio en `$LUMEN_STATE_DIR/oauth2c/`, una vez completada la retirada del callback. No borres `callback.json` antes de retirarlo: contiene la información sobre quién añadió la URI.
MD
add_cell code callback-remove <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_callback remove
CODE
add_cell markdown troubleshooting <<'MD'
## Diagnóstico y repetición

| Síntoma | Comprobación / acción |
|---|---|
| `oauth2c: command not found` | El PATH del kernel debe incluir `/opt/homebrew/bin` en Apple Silicon. Reinicia el kernel tras instalar. |
| No aparece la URL mientras espera | Usa el kernel local IPython 9. Como alternativa, ejecuta el contenido de la celda en Bash desde la raíz, sin la línea `%%bash`. |
| Callback rechazado | Repite la celda 3: el instalador de aplicaciones puede haber restaurado el callback único de Lumen. |
| Puerto 9876 ocupado | Termina la ejecución anterior de oauth2c; no cierres Lumen en 8088. |
| Lock después de interrumpir el kernel | Comprueba que ya no existe otro proceso oauth2c y retira únicamente el directorio vacío `.lock` dentro de `oauth2c/`. |
| OAuth `invalid_client` / HTTP 401 | Repite la lectura de credenciales; verifica que OBO usa el cliente STS. El helper obtiene otro token administrativo en cada preparación/retirada. |
| OAuth `invalid_grant` / token caducado | Repite login humano, token del actor e intercambio. No reutilices un authorization code. |
| `may_act` o `groups` ausentes | Comprueba el cliente OIDC, el usuario y los grupos; [capítulo 03](docs/manual/03-verify.md) y [04](docs/manual/04-vault-iam.md). |
| Vault 403 en la lectura RO | Revisa entidades, grupos, registro del agente, `actor-token.sub`, RAR y los [bloqueos](docs/manual/12-bloqueos.md). Obtener un JWT no demuestra autorización. |
| No hay refresh token | Es el comportamiento configurado en Lumen; repite Authorization Code + PKCE. |

Para repetir el recorrido, renueva los tokens en A/B/C; prepara de nuevo el callback si lo retiraste. El helper comprueba que los tokens de entrada tienen el issuer esperado y no han caducado. No cambia permisos para convertir una denegación en éxito.

**Alcance de la validación:** consulta el [informe del notebook](verify/docs/oauth2c-notebook-validation.json). Las pruebas locales usan el binario oauth2c real contra un servidor OAuth simulado, con secretos sintéticos. No equivalen a una ejecución contra tu tenant ni a una prueba real de los permisos de Vault.

Fuentes y mantenimiento:

- [oauth2c 1.21.1: documentación](https://github.com/SecureAuthCorp/oauth2c/tree/v1.21.1).
- [HashiCorp: IBM Verify y Agentic IAM](https://developer.hashicorp.com/vault/ai/iam/providers/verify).
- [Recorrido equivalente con curl y Vault CLI](docs/manual/11-obo.md).
- [Generador de este notebook](verify/scripts/build-oauth2c-notebook.sh). Regenerar desde la raíz con `bash verify/scripts/build-oauth2c-notebook.sh`; deja salidas y contadores vacíos.
MD
jq -n --slurpfile cells "$build_dir/cells.json" \
  '{cells:$cells[0],metadata:{kernelspec:{display_name:"Python 3 (ipykernel)",language:"python",name:"python3"},language_info:{name:"python"}},nbformat:4,nbformat_minor:5}' \
  > 10_OAuth2c_Verify_Vault.ipynb
printf 'Generado 10_OAuth2c_Verify_Vault.ipynb\n'
