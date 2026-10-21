#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
admin_login
app_token
APP_CLIENT_ID=$(jq -r .client_id "$TMP_WORK/app-credential.json")
api GET /v1.0/applications "$TMP_WORK/apps.json"
APP_ID=$(jq -er '[..|objects|select(.name?=="vault-authn-entry")|._links.self.href|split("/")[-1]]|unique|if length==1 then .[0] else error("Expected exactly one existing vault-authn-entry") end' "$TMP_WORK/apps.json")
api GET "/v1.0/applications/$APP_ID" "$TMP_WORK/app.json"
# Preserve the full app and its secret. Change only the settings needed by this lab.
jq --arg cid "$APP_CLIENT_ID" '
 .providers.oidc.token.accessTokenType="jwt" |
 .providers.oidc.token.attributeMappings=((.providers.oidc.token.attributeMappings//[]|map(select(.targetName!="may_act")))+[{targetName:"may_act",function:{custom:({client_id:$cid}|tojson)}}]) |
 .providers.oidc.properties.additionalConfig.responseTypes=["code"] |
 .providers.oidc.properties.additionalConfig.responseModes=["query"] |
 .providers.oidc.properties.additionalConfig.clientAuthMethod="client_secret_basic" |
 .providers.oidc.properties.grantTypes.authorizationCode="true" |
 .providers.oidc.properties.grantTypes.clientCredentials="true" |
 .providers.oidc.requirePkceVerification="true"
' "$TMP_WORK/app.json" > "$TMP_WORK/app-update.json"
api PUT "/v1.0/applications/$APP_ID" "$TMP_WORK/app-result.json" --data-binary "@$TMP_WORK/app-update.json"
api GET "/v1.0/applications/$APP_ID" "$TMP_WORK/app-check.json"
jq -e --arg cid "$APP_CLIENT_ID" '.providers.oidc.token.accessTokenType=="jwt" and any(.providers.oidc.token.attributeMappings[]; .targetName=="may_act" and (.function.custom|fromjson).client_id==$cid)' "$TMP_WORK/app-check.json" >/dev/null
printf 'OIDC app updated and read back: %s\n' "$APP_ID"
# Reconcile the known Lumen RAR schema, preserving its ID and other settings.
source "$VERIFY_DIR/scripts/rar-common.sh"
configure_rar
# STS client: token exchange only, no Verify administrative entitlements.
api GET /v1.0/sts/oauth/clients "$TMP_WORK/sts-list.json"
STS_ID=$(jq -r '[..|objects|select(.clientName?=="vault-obo-sts")|.clientId]|unique|if length>1 then error("Duplicate STS name") else .[0]//empty end' "$TMP_WORK/sts-list.json")
if [ -z "$STS_ID" ]; then
  api POST /v1.0/sts/oauth/clients "$TMP_WORK/sts-created.json" --data-binary "@$VERIFY_DIR/config/sts.json"
  STS_ID=$(awk 'tolower($1)=="location:" {gsub("\r", "", $2); n=split($2,a,"/"); print a[n]}' "$TMP_WORK/response.headers")
  [ -n "$STS_ID" ] || STS_ID=$(jq -er .clientId "$TMP_WORK/sts-created.json")
else
  api GET "/v1.0/sts/oauth/clients/$STS_ID" "$TMP_WORK/sts-existing.json"
  jq -s '.[0]*.[1]' "$TMP_WORK/sts-existing.json" "$VERIFY_DIR/config/sts.json" > "$TMP_WORK/sts-update.json"
  api PUT "/v1.0/sts/oauth/clients/$STS_ID" "$TMP_WORK/sts-updated.json" --data-binary "@$TMP_WORK/sts-update.json"
fi
api GET "/v1.0/sts/oauth/clients/$STS_ID" "$TMP_WORK/sts.json"
# API responses stay in a private temporary directory. Only credentials go to Vault.
jq -e --arg id "$STS_ID" --arg tenant "$TENANT" '{client_id:$id,client_secret:.clientAuthentication.clientSecret,tenant:$tenant}|select(.client_secret|type=="string" and length>0)' "$TMP_WORK/sts.json" | kv_write verify-sts
jq -n --arg app_id "$APP_ID" --arg sts_id "$STS_ID" --arg rar_id "$RAR_ID" '{application_id:$app_id,sts_client_id:$sts_id,rar_id:$rar_id}' | kv_write verify-config
jq -e '.enabled and .tokenExchangeSettings.actorTokenRequired and .tokenSettings.accessTokenType=="jwt" and .tokenSettings.restrictEntitlements and (.tokenSettings.entitlements|length==0)' "$TMP_WORK/sts.json" >/dev/null
printf 'STS configured and credentials stored in verify/secrets/verify-sts.\n'
