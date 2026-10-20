#!/usr/bin/env bash
# Verify authenticates the workload to Vault; Vault issues the SPIFFE JWT-SVID
# exchanged for a short-lived Claude bearer token.
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
for name in ANTHROPIC_FEDERATION_RULE_ID ANTHROPIC_ORGANIZATION_ID ANTHROPIC_SERVICE_ACCOUNT_ID ANTHROPIC_WORKSPACE_ID; do
  [ -n "${!name:-}" ] || fail "Configura $name según docs/manual/08-claude-spiffe.md"
done
: "${NGROK_DOMAIN:?Configura NGROK_DOMAIN}"
admin_login
api GET /v1.0/applications "$TMP_WORK/apps.json"
app_id=$(jq -r '[._embedded.applications[]|select(.name=="vault-chatbot-anthropic")|._links.self.href|split("/")[-1]]|if length>1 then error("Duplicate Anthropic application") else .[0]//empty end' "$TMP_WORK/apps.json")
if [ -z "$app_id" ]; then
  kv_read chatbot/research > "$TMP_WORK/research.json"
  template_id=$(jq -er .application_id "$TMP_WORK/research.json")
  api GET "/v1.0/applications/$template_id" "$TMP_WORK/template.json"
  jq '{name:"vault-chatbot-anthropic",templateId,applicationState,signonState,visibleOnLaunchpad:false,description:"Lumen Vault SPIFFE JWT-SVID issuer for Claude",providers,identitySources,approvalRequired:false,provisioningMode} |
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
  app_id=$(jq -er '._embedded.applications[]|select(.name=="vault-chatbot-anthropic")|._links.self.href|split("/")[-1]' "$TMP_WORK/apps.json")
fi
api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
jq -e '.providers.oidc.properties.grantTypes.clientCredentials=="true" and .providers.oidc.token.accessTokenType=="jwt" and .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes==true' "$TMP_WORK/app.json" >/dev/null
jq --arg id "$app_id" '{application_id:$id,client_id:.providers.oidc.properties.clientId,client_secret:.providers.oidc.properties.clientSecret}' "$TMP_WORK/app.json" | kv_write chatbot/anthropic
cid=$(jq -er .providers.oidc.properties.clientId "$TMP_WORK/app.json")
vault policy write chatbot-anthropic "$CHATBOT_DIR/policies/anthropic.hcl" >/dev/null
vault write identity/entity/name/chatbot-anthropic external_id="$cid" policies=chatbot-anthropic >/dev/null
entity=$(vault read -field=id identity/entity/name/chatbot-anthropic)
alias_id=$(vault read -format=json "identity/entity/id/$entity" | jq -r '.data.aliases[]?|select(.name=="chatbot-anthropic")|.id')
if [ -z "$alias_id" ]; then
  vault read -format=json sys/config/oauth-resource-server/verify | jq '.data|del(.config_id,.profile_name)' | vault write sys/config/oauth-resource-server/verify - >/dev/null
  vault write identity/entity-alias name=chatbot-anthropic canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid" >/dev/null
fi
jq -n --arg entity "$entity" '{display_name:"chatbot-anthropic",entity_id:$entity,ceiling_policies:["chatbot-anthropic"],no_default_ceiling_policy:true,optional_authorization_details:false,description:"Lumen workload: Vault SPIFFE JWT-SVID to Claude WIF"}' | vault write agent-registry/register - >/dev/null
vault policy write chatbot-bootstrap "$CHATBOT_DIR/policies/bootstrap.hcl" >/dev/null
jq -n --arg model "${LUMEN_ANTHROPIC_MODEL:-claude-haiku-5-5}" \
  --arg rule "$ANTHROPIC_FEDERATION_RULE_ID" --arg organization "$ANTHROPIC_ORGANIZATION_ID" \
  --arg service_account "$ANTHROPIC_SERVICE_ACCOUNT_ID" --arg workspace "$ANTHROPIC_WORKSPACE_ID" \
  --arg issuer "https://$NGROK_DOMAIN/v1/verify/spiffe" \
  --arg sub "spiffe://${SPIFFE_TRUST_DOMAIN:-lumen.demo}/ns/verify/agent/lumen-anthropic" \
  '{provider:"anthropic",model:$model,credential_source:"vault_spiffe",credential_path:"spiffe/role/lumen-anthropic/mintjwt",auth_flow:"spiffe_jwt_svid",federation_rule_id:$rule,organization_id:$organization,service_account_id:$service_account,workspace_id:$workspace,issuer:$issuer,spiffe_id:$sub,audience:"https://api.anthropic.com"}' | kv_write chatbot/model
echo 'Claude configurado: SPIFFE JWT-SVID y token RFC 7523; sin API key estática.'
