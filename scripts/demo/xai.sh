#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
sha=$("${K[@]}" -n vault exec vault-0 -- cat /vault/plugins/vault-plugin-secrets-xai.sha256 | tr -d '[:space:]')
vault plugin register -sha256="$sha" secret vault-plugin-secrets-xai >/dev/null
export VAULT_NAMESPACE=verify
if ! vault secrets list -format=json | jq -e 'has("xai/")' >/dev/null; then
  vault secrets enable -path=xai vault-plugin-secrets-xai >/dev/null
fi
jq -n '{management_api_key:env.XAI_MANAGEMENT_API_KEY} + (if (env.XAI_TEAM_ID//"")!="" then {team_id:env.XAI_TEAM_ID} else {} end)' | vault write xai/config - >/dev/null
# Keep the user's existing role. Defaults apply only on an empty deployment.
role_state='rol existente conservado'
if ! vault read xai/roles/lumen >/dev/null 2>&1; then
  printf '%s' '{"acls":["api-key:model:*","api-key:endpoint:*"],"ttl":"5m","max_ttl":"10m","set_native_expiry":true}' | vault write xai/roles/lumen - >/dev/null
  role_state='rol creado con TTL 5 min y máximo 10 min'
fi
vault read -format=json xai/roles/lumen | jq -e '.data.set_native_expiry and .data.max_ttl>=300 and (.data.acls|type=="array" and length>=2)' >/dev/null
echo "Plugin xAI preparado: $role_state; el chatbot solicita leases de 300 s."
