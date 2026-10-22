#!/usr/bin/env bash
# Optional identities; never updates the existing OIDC/research/model clients.
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
source "$CHATBOT_DIR/scripts/access-controls.sh"
kv_read chatbot/sts > "$TMP_WORK/sts.json"
jq -e '.client_id and .client_secret' "$TMP_WORK/sts.json" >/dev/null
vault read -format=json sys/config/oauth-resource-server/verify > "$TMP_WORK/profile.json"
jq -e '.data.actor_claim=="actor-token.sub" and .data.no_default_policy' "$TMP_WORK/profile.json" >/dev/null
admin_login
printf '[]' > "$TMP_WORK/entitlements.json"
for group in chatbot-readers chatbot-writers chatbot-supervisors; do
  api GET /v2.0/Groups "$TMP_WORK/group.json" --header 'Accept: application/scim+json' --get --data-urlencode "filter=displayName eq \"$group\""
  gid=$(jq -er --arg group "$group" '.Resources |
    if length==1 and .[0].displayName==$group then .[0].id else error("Grupo ausente o duplicado") end' "$TMP_WORK/group.json")
  jq --arg gid "$gid" '.+[{assignee:{subjectId:$gid,subjectType:"group"},grantType:"BRT"}]' \
    "$TMP_WORK/entitlements.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/entitlements.json"
done
jq -n --slurpfile additions "$TMP_WORK/entitlements.json" \
  '{birthRightAccess:false,requestAccess:false,additions:$additions[0]}' > "$TMP_WORK/grants.json"
initialize_block_policies
printf '{"version":1,"agents":{}}' > "$TMP_WORK/bundle.json"
for task in read write reveal; do
  name="vault-chatbot-task-$task"
  api GET /v1.0/applications "$TMP_WORK/apps.json"
  app_id=$(jq -er --arg name "$name" '[._embedded.applications[]|select(.name==$name)|._links.self.href|split("/")[-1]] |
    if length>1 then error("Duplicate task application") else .[0]//"" end' "$TMP_WORK/apps.json")
  if [ -z "$app_id" ]; then
    jq --arg name "$name" '{
      name:$name,templateId,applicationState,signonState,visibleOnLaunchpad:false,
      description:"Lumen optional task identity",providers,identitySources,approvalRequired:false,provisioningMode
    } | del(.providers.oidc.properties.clientId,.providers.oidc.properties.clientSecret) |
    .providers.oidc.token.attributeMappings=[] |
    .providers.oidc.applicationUrl="http://localhost:8088" |
    .providers.oidc.properties.redirectUris=["http://localhost:8088/auth/callback"] |
    .providers.oidc.properties.grantTypes.ropc="false"' "$VERIFY_DIR/config/oidc-template.json" > "$TMP_WORK/create.json"
    api POST /v1.0/applications "$TMP_WORK/created.json" --data-binary "@$TMP_WORK/create.json"
    api GET /v1.0/applications "$TMP_WORK/apps.json"
    app_id=$(jq -er --arg name "$name" '[._embedded.applications[]|select(.name==$name)|._links.self.href|split("/")[-1]] |
      if length==1 then .[0] else error("Task application absent or duplicated") end' "$TMP_WORK/apps.json")
  fi
  api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
  cid=$(jq -er '.providers.oidc.properties.clientId|select(type=="string" and length>0)' "$TMP_WORK/app.json")
  jq --arg cid "$cid" '
    .providers.oidc.applicationUrl="http://localhost:8088" |
    .providers.oidc.properties.redirectUris=["http://localhost:8088/auth/callback"] |
    .providers.oidc.properties.grantTypes |= with_entries(.value=(if (.key=="authorizationCode" or .key=="clientCredentials") then "true" else "false" end)) |
    .providers.oidc.properties.generateRefreshToken="false" |
    .providers.oidc.properties.accessTokenExpiry=600 |
    .providers.oidc.token.accessTokenType="jwt" |
    .providers.oidc.requirePkceVerification="true" |
    .providers.oidc.token.attributeMappings=[
      {targetName:"may_act",function:{custom:({client_id:$cid}|tojson)}},
      {targetName:"groups",sourceId:"4"}]
  ' "$TMP_WORK/app.json" > "$TMP_WORK/update.json"
  api PUT "/v1.0/applications/$app_id" "$TMP_WORK/updated.json" --data-binary "@$TMP_WORK/update.json"
  api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
  jq -e --arg cid "$cid" '
    .providers.oidc.properties.clientId==$cid and .providers.oidc.requirePkceVerification=="true" and
    .providers.oidc.token.accessTokenType=="jwt" and
    .providers.oidc.properties.grantTypes.authorizationCode=="true" and
    .providers.oidc.properties.grantTypes.clientCredentials=="true" and
    .providers.oidc.properties.grantTypes.ropc=="false" and
    (.providers.oidc.properties.clientSecret|type=="string" and length>0) and
    any(.providers.oidc.token.attributeMappings[]; .targetName=="may_act" and (.function.custom|fromjson).client_id==$cid)
  ' "$TMP_WORK/app.json" >/dev/null
  api POST "/v1.0/owner/applications/$app_id/entitlements" "$TMP_WORK/granted.json" --data-binary "@$TMP_WORK/grants.json"
  agent="chatbot-task-$task"
  policy="$agent"
  vault policy write "$policy" "$CHATBOT_DIR/policies/task-$task.hcl" >/dev/null
  # Actor tokens authenticate the agent at STS; entity policies grant no
  # autonomous access. Data permissions are obtained only through user OBO.
  vault write "identity/entity/name/$agent" external_id="$cid" policies="" >/dev/null
  entity=$(vault read -field=id "identity/entity/name/$agent")
  vault read -format=json "identity/entity/id/$entity" > "$TMP_WORK/entity.json"
  alias_id=$(jq -er --arg name "$agent" '[.data.aliases[]?|select(.name==$name)|.id] |
    if length>1 then error("Duplicate task alias") else .[0]//"" end' "$TMP_WORK/entity.json")
  if [ -z "$alias_id" ]; then
    vault write identity/entity-alias name="$agent" canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid" >/dev/null
  else
    # Vault 2.1 does not return issuer/external_id in the alias read response.
    # Check ownership, then reconcile that same alias ID through its write API.
    jq -e --arg id "$alias_id" --arg entity "$entity" \
      'any(.data.aliases[]; .id==$id and .canonical_id==$entity)' "$TMP_WORK/entity.json" >/dev/null ||
      fail "El alias existente de $agent pertenece a otra entidad."
    vault write "identity/entity-alias/id/$alias_id" name="$agent" canonical_id="$entity" \
      issuer="$TENANT/oauth2" external_id="$cid" >/dev/null
  fi
  jq -n --arg name "$agent" --arg entity "$entity" --arg policy "$policy" '{
    display_name:$name,entity_id:$entity,
    ceiling_policies:[$policy,"lumen-block-database-read","lumen-block-database-write","lumen-block-decrypt"],
    no_default_ceiling_policy:true,optional_authorization_details:false,
    description:"Lumen optional task agent; user OBO required"
  }' | vault write agent-registry/register - >/dev/null
  vault read -format=json "agent-registry/registration/display-name/$agent" > "$TMP_WORK/registration.json"
  jq -e --arg entity "$entity" --arg policy "$policy" \
    '.data.entity_id==$entity and .data.optional_authorization_details==false and (.data.ceiling_policies|index($policy)!=null)' \
    "$TMP_WORK/registration.json" >/dev/null
  jq --arg id "$app_id" --arg entity "$entity" --arg policy "$policy" \
    '{application_id:$id,client_id:.providers.oidc.properties.clientId,client_secret:.providers.oidc.properties.clientSecret,entity_id:$entity,ceiling_policy:$policy}' \
    "$TMP_WORK/app.json" > "$TMP_WORK/credential.json"
  jq --arg task "$task" --slurpfile credential "$TMP_WORK/credential.json" \
    '.agents[$task]=$credential[0]' "$TMP_WORK/bundle.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/bundle.json"
  printf 'Prepared %s\n' "$agent"
done
# Publish only a complete catalog, then allow the bootstrap to read this path.
kv_write chatbot/task-agents < "$TMP_WORK/bundle.json"
vault policy write chatbot-bootstrap "$CHATBOT_DIR/policies/bootstrap.hcl" >/dev/null
if vault kv metadata get -mount=secrets chatbot/personal-spaces >/dev/null 2>&1; then
  bash "$CHATBOT_DIR/scripts/configure-personal-spaces.sh"
fi
echo 'Task agents ready. Select one in the interface after restarting Lumen. Default: current mode.'
if vault kv metadata get -mount=secrets chatbot/contracts >/dev/null 2>&1; then
  bash "$CHATBOT_DIR/scripts/configure-contracts.sh"
fi
