#!/usr/bin/env bash
# Admin key is provisioning-only. WIF provider/mapping setup uses the documented UI.
source "$(dirname "$0")/common.sh"
load_inputs
: "${OPENAI_ADMIN_API_KEY:?Configura OPENAI_ADMIN_API_KEY}"
work=$(mktemp -d "$LUMEN_STATE_DIR/openai-admin.XXXXXX")
trap 'rm -rf "$work"' EXIT
printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$OPENAI_ADMIN_API_KEY" > "$work/headers"
request() {
  local method=$1 path=$2 output=$3; shift 3
  local code
  # Retry transient failures only for reads; never repeat resource creation.
  local retry=()
  [ "$method" != GET ] || retry=(--retry 3 --retry-delay 2 --retry-max-time 150)
  code=$(curl -sS --connect-timeout 10 --max-time 45 "${retry[@]}" -X "$method" --header "@$work/headers" \
    --output "$output" --write-out '%{http_code}' "$@" "https://api.openai.com/v1$path")
  case "$code" in 2??) ;; *) fail "OpenAI Admin API rechazó $method $path (HTTP $code)";; esac
}
list_all() {
  local path=$1 out=$2 after='' query
  printf '[]' > "$out"
  while :; do
    query='?limit=100'
    [ -z "$after" ] || query="$query&after=$after"
    request GET "$path$query" "$work/page.json"
    jq -e '.data|type=="array"' "$work/page.json" >/dev/null
    jq --slurpfile page "$work/page.json" '.+$page[0].data' "$out" > "$work/next.json"
    mv "$work/next.json" "$out"
    [ "$(jq -r '.has_more//false' "$work/page.json")" = true ] || break
    after=$(jq -er '.last_id//.data[-1].id' "$work/page.json")
    [[ "$after" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'Cursor de OpenAI no válido'
  done
}
list_all /organization/projects "$work/projects.json"
project=${OPENAI_PROJECT_ID:-}
if [ -z "$project" ]; then
  project=$(jq -r '[.[]|select(.name=="lumen-vault-demo" and .status=="active")]|if length>1 then error("Duplicate project") else .[0].id//empty end' "$work/projects.json")
  if [ -z "$project" ]; then
    request POST /organization/projects "$work/project.json" --data '{"name":"lumen-vault-demo"}'
    project=$(jq -er .id "$work/project.json")
  fi
fi
[[ "$project" =~ ^proj_[a-zA-Z0-9_-]+$ ]] || fail 'OPENAI_PROJECT_ID no válido'
request GET "/organization/projects/$project" "$work/project.json"
jq -e '.status=="active"' "$work/project.json" >/dev/null || fail 'El proyecto OpenAI no está activo'
list_all "/organization/projects/$project/service_accounts" "$work/accounts.json"
account=${OPENAI_SERVICE_ACCOUNT_ID:-}
if [ -z "$account" ]; then
  account=$(jq -r '[.[]|select(.name=="lumen-chatbot")]|if length>1 then error("Duplicate service account") else .[0].id//empty end' "$work/accounts.json")
  if [ -z "$account" ]; then
    request POST "/organization/projects/$project/service_accounts" "$work/account.json" --data '{"name":"lumen-chatbot"}'
    account=$(jq -er .id "$work/account.json")
    # This API creates a static key as a side effect; revoke only that new key.
    key_id=$(jq -er .api_key.id "$work/account.json")
    [[ "$key_id" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'ID de la nueva clave no válido'
    request DELETE "/organization/projects/$project/api_keys/$key_id" "$work/revoked.json"
  fi
fi
[[ "$account" =~ ^[a-zA-Z0-9_-]+$ ]] || fail 'OPENAI_SERVICE_ACCOUNT_ID no válido'
request GET "/organization/projects/$project/service_accounts/$account" "$work/account-check.json"
mkdir -p "$LUMEN_STATE_DIR/openai"
jq -n --arg project "$project" --arg account "$account" '{project_id:$project,service_account_id:$account}' > "$LUMEN_STATE_DIR/openai/resources.json"
# Replace only our non-secret IDs; all static integration inputs remain intact.
awk '!/^OPENAI_PROJECT_ID=/ && !/^OPENAI_SERVICE_ACCOUNT_ID=/' "$DEMO_ENV_FILE" > "$work/env"
jq -rn --arg p "$project" --arg s "$account" '"OPENAI_PROJECT_ID="+($p|@sh),"OPENAI_SERVICE_ACCOUNT_ID="+($s|@sh)' >> "$work/env"
cat "$work/env" > "$DEMO_ENV_FILE"
echo 'Proyecto y cuenta de servicio OpenAI preparados. No se conserva una API key de inferencia.'
cat "$LUMEN_STATE_DIR/openai/resources.json"
