#!/usr/bin/env bash
# Verify authenticates the workload to Vault; Vault issues the SPIFFE identity.
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
identity_only=false
case "${1:-}" in --identity-only) identity_only=true;; '') ;; *) fail 'Invalid argument';; esac
if [ "$identity_only" = false ]; then
  : "${OPENAI_IDENTITY_PROVIDER_ID:?Set the OpenAI Workload Identity Provider}"
  : "${OPENAI_SERVICE_ACCOUNT_ID:?Set the OpenAI service account mapping}"
fi
: "${NGROK_DOMAIN:?Set NGROK_DOMAIN}"
admin_login
api GET /v1.0/applications "$TMP_WORK/apps.json"
app_id=$(jq -r '[._embedded.applications[]|select(.name=="vault-chatbot-openai")|._links.self.href|split("/")[-1]]|if length>1 then error("Duplicate OpenAI application") else .[0]//empty end' "$TMP_WORK/apps.json")
if [ -z "$app_id" ]; then
  kv_read chatbot/research > "$TMP_WORK/research.json"
  template_id=$(jq -er .application_id "$TMP_WORK/research.json")
  api GET "/v1.0/applications/$template_id" "$TMP_WORK/template.json"
  jq '{name:"vault-chatbot-openai",templateId,applicationState,signonState,visibleOnLaunchpad:false,description:"Lumen Vault SPIFFE JWT-SVID issuer",providers,identitySources,approvalRequired:false,provisioningMode} |
      del(.providers.oidc.properties.clientId,.providers.oidc.properties.clientSecret) |
      .providers.oidc.properties.grantTypes |= with_entries(.value=(if .key=="clientCredentials" then "true" else "false" end)) |
      .providers.oidc.properties.generateRefreshToken="false" |
      .providers.oidc.token.attributeMappings=[] |
      .providers.oidc.properties.accessTokenExpiry=300 |
      .providers.oidc.token.accessTokenType="jwt" |
      .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes=true |
      .providers.oidc.properties.additionalConfig.ignoreUnknownAuthDetailTypes=false |
      .providers.oidc.properties.additionalConfig.authDetailTypes=[{type:"vault:path_access"}]' "$TMP_WORK/template.json" > "$TMP_WORK/create.json"
  api POST /v1.0/applications "$TMP_WORK/created.json" --data-binary "@$TMP_WORK/create.json"
  api GET /v1.0/applications "$TMP_WORK/apps.json"
  app_id=$(jq -er '._embedded.applications[]|select(.name=="vault-chatbot-openai")|._links.self.href|split("/")[-1]' "$TMP_WORK/apps.json")
fi
api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
jq -e '.providers.oidc.properties.grantTypes.clientCredentials=="true" and .providers.oidc.token.accessTokenType=="jwt" and .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes==true' "$TMP_WORK/app.json" >/dev/null
jq --arg id "$app_id" '{application_id:$id,client_id:.providers.oidc.properties.clientId,client_secret:.providers.oidc.properties.clientSecret}' "$TMP_WORK/app.json" | kv_write chatbot/openai
cid=$(jq -er .providers.oidc.properties.clientId "$TMP_WORK/app.json")
vault policy write chatbot-openai "$CHATBOT_DIR/policies/openai.hcl" >/dev/null
vault write identity/entity/name/chatbot-openai external_id="$cid" policies=chatbot-openai >/dev/null
entity=$(vault read -field=id identity/entity/name/chatbot-openai)
alias_id=$(vault read -format=json "identity/entity/id/$entity" | jq -r '.data.aliases[]?|select(.name=="chatbot-openai")|.id')
if [ -z "$alias_id" ]; then
  vault read -format=json sys/config/oauth-resource-server/verify | jq '.data|del(.config_id,.profile_name,.mount_accessor)' | vault write sys/config/oauth-resource-server/verify - >/dev/null
  vault write identity/entity-alias name=chatbot-openai canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid" >/dev/null
fi
jq -n --arg entity "$entity" '{display_name:"chatbot-openai",entity_id:$entity,ceiling_policies:["chatbot-openai"],no_default_ceiling_policy:true,optional_authorization_details:false,description:"Lumen workload: Vault SPIFFE JWT-SVID to OpenAI WIF"}' | vault write agent-registry/register - >/dev/null
vault policy write chatbot-bootstrap "$CHATBOT_DIR/policies/bootstrap.hcl" >/dev/null
[ "$identity_only" = false ] || { echo 'chatbot-openai identity ready; active provider unchanged.'; exit 0; }
jq -n --arg model "${LUMEN_OPENAI_MODEL:-gpt-5.6-luna}" --arg provider "$OPENAI_IDENTITY_PROVIDER_ID" --arg service_account "$OPENAI_SERVICE_ACCOUNT_ID" \
  --arg issuer "https://$NGROK_DOMAIN/v1/verify/spiffe" --arg sub "spiffe://${SPIFFE_TRUST_DOMAIN:-lumen.demo}/ns/verify/agent/lumen-openai" \
  '{provider:"openai",model:$model,credential_source:"vault_spiffe",credential_path:"spiffe/role/lumen-openai/mintjwt",auth_flow:"spiffe_jwt_svid",identity_provider_id:$provider,service_account_id:$service_account,issuer:$issuer,spiffe_id:$sub,audience:"https://api.openai.com/v1"}' | model_profile_write
echo 'OpenAI configured: SPIFFE JWT-SVID and token exchange; no static inference API key.'
