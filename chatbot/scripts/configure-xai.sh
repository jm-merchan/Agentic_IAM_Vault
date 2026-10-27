#!/usr/bin/env bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
# Notebook 4 owns the plugin/configuration and its management key.
vault read -format=json xai/config > "$TMP_WORK/config.json"
vault read -format=json xai/roles/lumen > "$TMP_WORK/role.json"
# The role (ACLs, TTL and native expiry) is managed exclusively in notebook 4.

admin_login
api GET /v1.0/applications "$TMP_WORK/apps.json"
app_id=$(jq -r '[._embedded.applications[]|select(.name=="vault-chatbot-xai")|._links.self.href|split("/")[-1]]|if length>1 then error("Duplicate xAI application") else .[0]//empty end' "$TMP_WORK/apps.json")
if [ -z "$app_id" ]; then
  kv_read chatbot/research > "$TMP_WORK/research.json"
  template_id=$(jq -er .application_id "$TMP_WORK/research.json")
  api GET "/v1.0/applications/$template_id" "$TMP_WORK/template.json"
  jq '{name:"vault-chatbot-xai",templateId,applicationState,signonState,visibleOnLaunchpad:false,description:"Lumen dynamic xAI credentials via Vault",providers,identitySources,approvalRequired:false,provisioningMode} |
      del(.providers.oidc.properties.clientId,.providers.oidc.properties.clientSecret) |
      .providers.oidc.properties.grantTypes |= with_entries(.value=(if .key=="clientCredentials" then "true" else "false" end)) |
      .providers.oidc.properties.generateRefreshToken="false" |
      .providers.oidc.token.attributeMappings=[] |
      .providers.oidc.properties.accessTokenExpiry=600 |
      .providers.oidc.token.accessTokenType="jwt"' "$TMP_WORK/template.json" > "$TMP_WORK/create.json"
  api POST /v1.0/applications "$TMP_WORK/created.json" --data-binary "@$TMP_WORK/create.json"
  api GET /v1.0/applications "$TMP_WORK/apps.json"
  app_id=$(jq -er '._embedded.applications[]|select(.name=="vault-chatbot-xai")|._links.self.href|split("/")[-1]' "$TMP_WORK/apps.json")
fi
api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
jq '.providers.oidc.properties.additionalConfig.restrictAuthDetailTypes=true |
    .providers.oidc.properties.additionalConfig.ignoreUnknownAuthDetailTypes=false |
    .providers.oidc.properties.additionalConfig.authDetailTypes=[{type:"vault:path_access"}]' "$TMP_WORK/app.json" > "$TMP_WORK/update.json"
api PUT "/v1.0/applications/$app_id" "$TMP_WORK/updated.json" --data-binary "@$TMP_WORK/update.json"
api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
jq -e '.providers.oidc.properties.grantTypes.clientCredentials=="true" and .providers.oidc.token.accessTokenType=="jwt"' "$TMP_WORK/app.json" >/dev/null
jq --arg id "$app_id" '{application_id:$id,client_id:.providers.oidc.properties.clientId,client_secret:.providers.oidc.properties.clientSecret}' "$TMP_WORK/app.json" | kv_write chatbot/xai
if ! vault kv metadata get -mount=secrets chatbot/xai-access >/dev/null 2>&1; then
  openssl rand -hex 16 | jq -Rn '{generation:input}' | kv_write chatbot/xai-access
fi
bash "$CHATBOT_DIR/scripts/register-xai-agent.sh"
jq -n --arg model "${LUMEN_XAI_MODEL:-grok-4.3}" '{provider:"xai",model:$model,credential_source:"vault_dynamic",credential_path:"xai/creds/lumen",credential_ttl:300,auth_flow:"client_credentials"}' | model_profile_write
echo 'xAI configured: cached dynamic credentials, replaced before insufficient validity. Restart Lumen.'
