#!/usr/bin/env bash
# Shared setup for independent %%bash cells; compatible with macOS Bash 3.2.
set +x
set -euo pipefail
umask 077
OAUTH2C_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
lab_fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for tool in oauth2c vault curl jq openssl python3; do
  command -v "$tool" >/dev/null || lab_fail "Falta $tool en el PATH del kernel."
done
if [ -f "$OAUTH2C_ROOT/.env" ]; then source "$OAUTH2C_ROOT/.env"; fi
LUMEN_STATE_DIR=${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}
VAULT_ENV_FILE=${VAULT_ENV_FILE:-$LUMEN_STATE_DIR/vault/config.env}
[ -f "$VAULT_ENV_FILE" ] || lab_fail "Falta $VAULT_ENV_FILE. Prepara el laboratorio Lumen."
source "$VAULT_ENV_FILE"
: "${VAULT_ADDR:?Falta VAULT_ADDR}" "${VAULT_CACERT:?Falta VAULT_CACERT}" "${VAULT_TOKEN:?Falta VAULT_TOKEN}"
: "${VERIFY_TENANT:?Falta VERIFY_TENANT en .env o en el entorno del kernel}"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
TENANT=${VERIFY_TENANT%/}
ISSUER="$TENANT/oauth2"
LAB="$LUMEN_STATE_DIR/oauth2c"
CALLBACK=http://localhost:9876/callback
mkdir -p "$LAB"
chmod 700 "$LAB"
mkdir "$LAB/.lock" 2>/dev/null || lab_fail "Otra celda oauth2c está en marcha. Si interrumpiste el kernel, comprueba sus procesos antes de retirar $LAB/.lock."
WORK=$(mktemp -d "$LAB/.work.XXXXXX")
trap 'rm -rf "$WORK"; rmdir "$LAB/.lock"' EXIT

lab_credential() {
  # Read from Vault in every cell; no hard-coded or exported client credentials.
  local name=$1 path=$2
  vault kv get -format=json -mount=secrets "$path" > "$WORK/credential.json"
  jq -e '
    .data.data |
    if (.client_id|type=="string" and length>0) and
       (.client_secret|type=="string" and length>0)
    then {client_id,client_secret}
    else error("Credencial OAuth incompleta en Vault") end
  ' "$WORK/credential.json" > "$WORK/client.json"
  mv "$WORK/client.json" "$LAB/$name-client.json"
  CLIENT_ID=$(jq -er .client_id "$LAB/$name-client.json")
  CLIENT_SECRET=$(jq -er .client_secret "$LAB/$name-client.json")
}

lab_claims() {
  # Inspection only: Vault validates the signature when the token is used.
  local file=$1 part
  part=$(jq -er '.access_token | select(type=="string" and length>0) | split(".") |
    if length==3 then .[1] else error("El access token no es un JWT") end' "$file")
  part=$(printf '%s' "$part" | tr '_-' '/+')
  while [ $((${#part} % 4)) -ne 0 ]; do part="${part}="; done
  printf '%s' "$part" | openssl base64 -d -A | jq -e .
}

lab_require_token() {
  local name=$1
  [ -s "$LAB/$name.json" ] || lab_fail "Falta $name.json. Ejecuta primero la celda que lo obtiene."
  lab_claims "$LAB/$name.json" > "$WORK/$name-claims.json"
  jq -e --arg issuer "$ISSUER" --argjson now "$(date +%s)" '
    .iss==$issuer and (.sub|type=="string" and length>0) and
    (.exp|type=="number") and .exp>($now+15)
  ' "$WORK/$name-claims.json" >/dev/null ||
    lab_fail "$name: issuer inesperado o token caducado/a punto de caducar; repite su celda."
}

lab_save_token() {
  local name=$1 file=$2
  jq -e '.access_token|type=="string" and length>0' "$file" >/dev/null ||
    lab_fail "oauth2c no devolvió access_token; no se conserva una respuesta anterior."
  lab_claims "$file" | jq -e --arg issuer "$ISSUER" --argjson now "$(date +%s)" '
    .iss==$issuer and (.sub|type=="string" and length>0) and
    (.exp|type=="number") and .exp>($now+15)
  ' >/dev/null || lab_fail "Token de $name caducado o con issuer inesperado."
  mv "$file" "$LAB/$name.json"
  printf 'Guardado %s.json\n' "$name"
  jq '{token_type,expires_in,scope,refresh_token_present:has("refresh_token")}' "$LAB/$name.json"
  lab_claims "$LAB/$name.json" | jq '{iss,sub,exp,groups,may_act,"actor-token",authorization_details}'
}

lab_port_free() {
  python3 - <<'PY'
import socket
with socket.socket() as listener:
    # Match Go's listener behavior: TIME_WAIT is not an active callback server.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", 9876))
    except OSError:
        raise SystemExit("Puerto 9876 ocupado. Cierra su callback anterior antes de continuar.")
PY
}

lab_admin() {
  lab_credential admin verify-admin
  oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
    --grant-type client_credentials \
    --auth-method client_secret_basic --silent > "$WORK/admin-token.json"
  jq -er '"Authorization: Bearer "+(.access_token|select(type=="string" and length>0))+
    "\nContent-Type: application/json\nAccept: application/json"' \
    "$WORK/admin-token.json" > "$WORK/admin.headers"
  # Administrative credential is only needed during callback preparation/removal.
  rm -f "$LAB/admin-client.json"
}

lab_api() {
  local method=$1 path=$2 output=$3
  shift 3
  local status
  status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
    --request "$method" --header "@$WORK/admin.headers" --output "$output" \
    --write-out '%{http_code}' "$@" "$TENANT$path") ||
    lab_fail "No se ha podido conectar con Verify."
  case "$status" in
    2??) ;;
    *) lab_fail "Verify: HTTP $status en $method $path. No se continúa con una respuesta inválida." ;;
  esac
}

lab_callback() {
  local action=$1 app_id present=false owned=false
  case "$action" in add|remove) ;; *) lab_fail 'Callback: usa add o remove.' ;; esac
  if [ "$action" = remove ] && [ ! -f "$LAB/callback.json" ]; then
    printf 'No hay callback registrado por este notebook que retirar.\n'
    return
  fi
  vault kv get -format=json -mount=secrets chatbot/oidc > "$WORK/oidc.json"
  app_id=$(jq -er '.data.data.application_id|select(type=="string" and test("^[A-Za-z0-9_-]+$"))' "$WORK/oidc.json")
  if [ -f "$LAB/callback.json" ]; then
    jq -e --arg tenant "$TENANT" --arg id "$app_id" --arg uri "$CALLBACK" '
      .tenant==$tenant and .application_id==$id and .uri==$uri
    ' "$LAB/callback.json" >/dev/null ||
      lab_fail 'El registro del callback pertenece a otra instalación; no se modifica Verify.'
    owned=$(jq -r .added "$LAB/callback.json")
  fi
  lab_admin
  lab_api GET "/v1.0/applications/$app_id" "$WORK/app.json"
  jq -e '.name=="vault-chatbot-oidc" and
    (.providers.oidc.properties.redirectUris|type=="array")' "$WORK/app.json" >/dev/null ||
    lab_fail 'La aplicación no es vault-chatbot-oidc o su configuración no es válida.'
  if jq -e --arg uri "$CALLBACK" '.providers.oidc.properties.redirectUris|index($uri)!=null' "$WORK/app.json" >/dev/null; then present=true; fi
  if [ "$action" = add ]; then
    [ "$present" = true ] || owned=true
    jq -n --arg tenant "$TENANT" --arg id "$app_id" --arg uri "$CALLBACK" --argjson added "$owned" \
      '{tenant:$tenant,application_id:$id,uri:$uri,added:$added}' > "$WORK/callback.json"
    mv "$WORK/callback.json" "$LAB/callback.json"
    if [ "$present" = false ]; then
      jq --arg uri "$CALLBACK" '.providers.oidc.properties.redirectUris += [$uri]' "$WORK/app.json" > "$WORK/update.json"
      lab_api PUT "/v1.0/applications/$app_id" "$WORK/result.json" --data-binary "@$WORK/update.json"
    fi
    lab_api GET "/v1.0/applications/$app_id" "$WORK/checked.json"
    jq -e --arg uri "$CALLBACK" '
      (.providers.oidc.properties.redirectUris|index($uri)!=null) and
      .providers.oidc.properties.grantTypes.authorizationCode=="true"
    ' "$WORK/checked.json" >/dev/null || lab_fail 'El callback o Authorization Code no están habilitados.'
    printf 'Callback preparado: %s (añadido por este notebook: %s).\n' "$CALLBACK" "$owned"
  else
    if [ "$owned" = true ] && [ "$present" = true ]; then
      # Read/modify the current resource, never restore a stale whole-app backup.
      jq --arg uri "$CALLBACK" '.providers.oidc.properties.redirectUris |= map(select(.!=$uri))' "$WORK/app.json" > "$WORK/update.json"
      lab_api PUT "/v1.0/applications/$app_id" "$WORK/result.json" --data-binary "@$WORK/update.json"
      lab_api GET "/v1.0/applications/$app_id" "$WORK/checked.json"
      jq -e --arg uri "$CALLBACK" '.providers.oidc.properties.redirectUris|index($uri)==null' "$WORK/checked.json" >/dev/null ||
        lab_fail 'No se ha retirado el callback; se conserva el registro para reintentar.'
      printf 'Retirado únicamente el callback temporal de oauth2c.\n'
    else
      printf 'No se retira ningún callback: ya existía antes o ya no está presente.\n'
    fi
    rm -f "$LAB/callback.json"
  fi
}
