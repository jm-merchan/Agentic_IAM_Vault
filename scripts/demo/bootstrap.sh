#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
if ! vault namespace lookup verify >/dev/null 2>&1; then vault namespace create verify >/dev/null; fi
export VAULT_NAMESPACE=verify
if ! vault secrets list -format=json | jq -e '."secrets/".type=="kv" and ."secrets/".options.version=="2"' >/dev/null; then
  vault secrets enable -path=secrets -version=2 kv >/dev/null
fi
work=$(mktemp -d "$LUMEN_STATE_DIR/import.XXXXXX")
trap 'rm -rf "$work"' EXIT
put_if_changed() {
  local path=$1
  jq -S . > "$work/wanted.json"
  if vault kv get -format=json -mount=secrets "$path" > "$work/current.json" 2>/dev/null; then
    jq -S .data.data "$work/current.json" > "$work/current-data.json"
    if cmp -s "$work/current-data.json" "$work/wanted.json"; then return; fi
  fi
  vault kv put -mount=secrets "$path" - < "$work/wanted.json" >/dev/null
}
jq -n '{client_id:env.VERIFY_ADMIN_CLIENT_ID,client_secret:env.VERIFY_ADMIN_CLIENT_SECRET,tenant:env.VERIFY_TENANT}' | put_if_changed verify-admin
if [ -n "${XAI_MANAGEMENT_API_KEY:-}" ]; then jq -n '{API_KEY:env.XAI_MANAGEMENT_API_KEY}' | put_if_changed xai_mgmt; fi
if [ -n "${OPENAI_ADMIN_API_KEY:-}" ]; then jq -n '{api_key:env.OPENAI_ADMIN_API_KEY}' | put_if_changed openai-admin; fi
jq -n '{TAVILY_API_KEY:env.TAVILY_API_KEY}' | put_if_changed tavily
for role in reader writer supervisor; do
  if ! vault kv metadata get -mount=secrets "chatbot/users/$role" >/dev/null 2>&1; then
    env_name="LUMEN_$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')_PASSWORD"
    jq -n --arg role "$role" --arg env_name "$env_name" '{username:("lumen-"+$role),password:env[$env_name],provider:"Cloud Directory"}' | put_if_changed "chatbot/users/$role"
  fi
done
echo 'Entradas de .env importadas a verify/secrets; sin claves de inferencia estáticas.'
