#!/usr/bin/env bash
# Reconcile Verify group membership into Vault identity groups. Run after membership changes.
source "$(dirname "$0")/../../verify/scripts/common.sh"
admin_login
kv_read chatbot/runtime > "$TMP_WORK/runtime.json"
app_id=$(kv_read chatbot/oidc | jq -er .application_id)
printf '[]' > "$TMP_WORK/entitlements.json"
for level in readonly readwrite sensitive; do
  group=chatbot-readers; policy=chatbot-reader
  case "$level" in
    readwrite) group=chatbot-writers; policy=chatbot-writer ;;
    sensitive) group=chatbot-supervisors; policy=chatbot-supervisor ;;
  esac
  api GET /v2.0/Groups "$TMP_WORK/list.json" --header 'Accept: application/scim+json' --get --data-urlencode "filter=displayName eq \"$group\""
  gid=$(jq -er '.Resources|if length==1 then .[0].id else error("Expected one group") end' "$TMP_WORK/list.json")
  jq --arg gid "$gid" '.+[{assignee:{subjectId:$gid,subjectType:"group"},grantType:"BRT"}]' "$TMP_WORK/entitlements.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/entitlements.json"
  api GET "/v2.0/Groups/$gid" "$TMP_WORK/group.json" --header 'Accept: application/scim+json'
  printf '[]' > "$TMP_WORK/entities.json"
  for uid in $(jq -r '.members[]?|select(.type=="user" or .type==null)|.value' "$TMP_WORK/group.json"); do
    [[ "$uid" =~ ^[A-Za-z0-9-]+$ ]] || fail 'Unexpected user identifier'
    api GET "/v2.0/Users/$uid" "$TMP_WORK/user.json" --header 'Accept: application/scim+json'
    jq -e '.active' "$TMP_WORK/user.json" >/dev/null || continue
    name="chatbot-human-$uid"
    vault write "identity/entity/name/$name" external_id="$uid" policies='' >/dev/null
    entity=$(vault read -field=id "identity/entity/name/$name")
    alias=$(vault read -format=json "identity/entity/id/$entity" | jq -r --arg name "$name" '.data.aliases[]?|select(.name==$name)|.id')
    if [ -z "$alias" ]; then
      vault write identity/entity-alias name="$name" canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$uid" >/dev/null
    fi
    jq --arg entity "$entity" '.+[$entity]' "$TMP_WORK/entities.json" > "$TMP_WORK/next.json"
    mv "$TMP_WORK/next.json" "$TMP_WORK/entities.json"
  done
  jq -n --arg policy "$policy" --slurpfile entities "$TMP_WORK/entities.json" '{type:"internal",policies:[$policy],member_entity_ids:$entities[0]}' | vault write "identity/group/name/$group" - >/dev/null
  jq --arg level "$level" --arg name "$group" --arg gid "$gid" '.groups[$level]=[$name,$gid]' "$TMP_WORK/runtime.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/runtime.json"
  printf 'Synchronized %s: %s members, policy %s.\n' "$group" "$(jq length "$TMP_WORK/entities.json")" "$policy"
done
jq -n --slurpfile additions "$TMP_WORK/entitlements.json" '{birthRightAccess:false,requestAccess:false,additions:$additions[0]}' > "$TMP_WORK/grants.json"
api POST "/v1.0/owner/applications/$app_id/entitlements" "$TMP_WORK/granted.json" --data-binary "@$TMP_WORK/grants.json"
cat "$TMP_WORK/runtime.json" | kv_write chatbot/runtime
echo 'Restart Lumen to load the group ID mapping; users must obtain fresh OIDC sessions after changes.'
