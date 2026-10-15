#!/usr/bin/env bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
admin_login
cp "$VERIFY_DIR/config/oidc-template.json" "$TMP_WORK/template.json"
for suffix in oidc research; do
  name="vault-chatbot-$suffix"
  api GET /v1.0/applications "$TMP_WORK/apps.json"
  app_id=$(jq -r --arg name "$name" '[._embedded.applications[]|select(.name==$name)|._links.self.href|split("/")[-1]]|if length>1 then error("Duplicate application") else .[0]//empty end' "$TMP_WORK/apps.json")
  if [ -z "$app_id" ]; then
    jq --arg name "$name" '{name:$name,templateId,applicationState,signonState,visibleOnLaunchpad:false,description:"Vault IAM chatbot laboratory",providers,identitySources,approvalRequired:false,provisioningMode} | del(.providers.oidc.properties.clientId,.providers.oidc.properties.clientSecret) | .providers.oidc.token.attributeMappings=[] | .providers.oidc.applicationUrl="http://localhost:8088" | .providers.oidc.properties.redirectUris=["http://localhost:8088/auth/callback"] | .providers.oidc.properties.grantTypes.ropc="false"' "$TMP_WORK/template.json" > "$TMP_WORK/create-app.json"
    api POST /v1.0/applications "$TMP_WORK/created.json" --data-binary "@$TMP_WORK/create-app.json"
    api GET /v1.0/applications "$TMP_WORK/apps.json"
    app_id=$(jq -er --arg name "$name" '._embedded.applications[]|select(.name==$name)|._links.self.href|split("/")[-1]' "$TMP_WORK/apps.json")
  fi
  api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
  cid=$(jq -er .providers.oidc.properties.clientId "$TMP_WORK/app.json")
  jq --arg cid "$cid" --arg suffix "$suffix" '
    .providers.oidc.applicationUrl="http://localhost:8088" |
    .providers.oidc.properties.redirectUris=["http://localhost:8088/auth/callback"] |
    .providers.oidc.properties.grantTypes.ropc="false" |
    .providers.oidc.properties.grantTypes.authorizationCode=(if $suffix=="oidc" then "true" else "false" end) |
    .providers.oidc.properties.grantTypes.clientCredentials="true" |
    .providers.oidc.properties.generateRefreshToken="false" |
    .providers.oidc.token.attributeMappings=(if $suffix=="oidc" then [{targetName:"may_act",function:{custom:({client_id:$cid}|tojson)}},{targetName:"groups",sourceId:"4"}] else [] end) |
    .providers.oidc.properties.accessTokenExpiry=600 |
    .providers.oidc.token.accessTokenType="jwt" |
    .providers.oidc.requirePkceVerification="true"
  ' "$TMP_WORK/app.json" > "$TMP_WORK/update.json"
  api PUT "/v1.0/applications/$app_id" "$TMP_WORK/updated.json" --data-binary "@$TMP_WORK/update.json"
  api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
  jq --arg id "$app_id" '{application_id:$id,client_id:.providers.oidc.properties.clientId,client_secret:.providers.oidc.properties.clientSecret}' "$TMP_WORK/app.json" | kv_write "chatbot/$suffix"
  printf 'Configured %s (%s)\n' "$name" "$app_id"
done
api GET /v1.0/sts/oauth/clients "$TMP_WORK/sts-list.json"
sts_id=$(jq -r '[.clients[]|select(.clientName=="vault-chatbot-sts")|.clientId]|if length>1 then error("Duplicate STS") else .[0]//empty end' "$TMP_WORK/sts-list.json")
jq '.clientName="vault-chatbot-sts" | .tokenSettings.introspectMap += [{name:"groups",function:{custom:"requestContext[\"subject_token\"].groups"}}]' "$VERIFY_DIR/config/sts.json" > "$TMP_WORK/sts-payload.json"
if [ -z "$sts_id" ]; then
  api POST /v1.0/sts/oauth/clients "$TMP_WORK/sts-created.json" --data-binary "@$TMP_WORK/sts-payload.json"
  sts_id=$(awk 'tolower($1)=="location:"{gsub("\r","",$2);n=split($2,a,"/");print a[n]}' "$TMP_WORK/response.headers")
else
  api GET "/v1.0/sts/oauth/clients/$sts_id" "$TMP_WORK/sts-current.json"
  jq -s '.[0]*.[1]' "$TMP_WORK/sts-current.json" "$TMP_WORK/sts-payload.json" > "$TMP_WORK/sts-update.json"
  api PUT "/v1.0/sts/oauth/clients/$sts_id" "$TMP_WORK/sts-updated.json" --data-binary "@$TMP_WORK/sts-update.json"
fi
api GET "/v1.0/sts/oauth/clients/$sts_id" "$TMP_WORK/sts.json"
jq --arg id "$sts_id" '{client_id:$id,client_secret:.clientAuthentication.clientSecret}' "$TMP_WORK/sts.json" | kv_write chatbot/sts
echo 'OIDC, autonomous research client and STS credentials stored in Vault.'
