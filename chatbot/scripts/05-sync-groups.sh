#!/usr/bin/env bash
# Reconcile Verify group membership into Vault identity groups. Run after membership changes.
source "$(dirname "$0")/../../verify/scripts/common.sh"
case "${1:-}" in ''|--check) ;; *) fail 'Uso: 05-sync-groups.sh [--check]';; esac
admin_login
kv_read chatbot/runtime > "$TMP_WORK/runtime.json" ||
  fail 'No se pudo leer chatbot/runtime; completa la configuración de sesión del capítulo 04.'
jq -e '.session_secret|type=="string" and length>0' "$TMP_WORK/runtime.json" >/dev/null ||
  fail 'Falta una configuración runtime válida; ejecuta el paso agentes.'
kv_read chatbot/oidc > "$TMP_WORK/oidc.json" ||
  fail 'No se pudo leer chatbot/oidc; completa el paso oidc del capítulo 03.'
app_id=$(jq -er '.application_id|select(type=="string" and length>0)' "$TMP_WORK/oidc.json")
printf '[]' > "$TMP_WORK/entitlements.json"
# Resolve every group and member before the first Vault/Verify write. A missing
# third group must not leave the first two synchronized and the runtime stale.
for level in readonly readwrite sensitive; do
  group=chatbot-readers; policy=chatbot-reader
  case "$level" in
    readwrite) group=chatbot-writers; policy=chatbot-writer ;;
    sensitive) group=chatbot-supervisors; policy=chatbot-supervisor ;;
  esac
  vault policy read "$policy" >/dev/null ||
    fail "Falta la política $policy; ejecuta el paso agentes."
  api GET /v2.0/Groups "$TMP_WORK/list.json" --header 'Accept: application/scim+json' --get --data-urlencode "filter=displayName eq \"$group\""
  gid=$(jq -er --arg group "$group" '.Resources | if type=="array" and length==1 and .[0].displayName==$group then .[0].id else error("Grupo ausente o duplicado: "+$group+"; ejecuta el paso usuarios") end' "$TMP_WORK/list.json")
  [[ "$gid" =~ ^[A-Za-z0-9-]+$ ]] || fail "ID de grupo no válido: $group"
  jq --arg gid "$gid" '.+[{assignee:{subjectId:$gid,subjectType:"group"},grantType:"BRT"}]' "$TMP_WORK/entitlements.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/entitlements.json"
  api GET "/v2.0/Groups/$gid" "$TMP_WORK/group-$level.json" --header 'Accept: application/scim+json'
  jq -e --arg gid "$gid" --arg group "$group" '.id==$gid and .displayName==$group and ((.members//[])|type=="array")' "$TMP_WORK/group-$level.json" >/dev/null
  printf '[]' > "$TMP_WORK/active-$level.json"
  for uid in $(jq -r '.members[]?|select(.type=="user" or .type==null)|.value' "$TMP_WORK/group-$level.json"); do
    [[ "$uid" =~ ^[A-Za-z0-9-]+$ ]] || fail 'Unexpected user identifier'
    api GET "/v2.0/Users/$uid" "$TMP_WORK/user.json" --header 'Accept: application/scim+json'
    jq -e --arg uid "$uid" '.id==$uid and (.active|type=="boolean")' "$TMP_WORK/user.json" >/dev/null
    jq -e '.active' "$TMP_WORK/user.json" >/dev/null || continue
    jq --arg uid "$uid" '.+[$uid]|unique' "$TMP_WORK/active-$level.json" > "$TMP_WORK/next.json"
    mv "$TMP_WORK/next.json" "$TMP_WORK/active-$level.json"
  done
  printf 'Comprobado %s: %s usuarios activos; política %s disponible.\n' "$group" "$(jq length "$TMP_WORK/active-$level.json")" "$policy"
done
if [ "${1:-}" = --check ]; then
  echo 'Requisitos de grupos comprobados. No se han modificado entidades, permisos ni runtime.'
  exit 0
fi
for level in readonly readwrite sensitive; do
  group=chatbot-readers; policy=chatbot-reader
  case "$level" in
    readwrite) group=chatbot-writers; policy=chatbot-writer ;;
    sensitive) group=chatbot-supervisors; policy=chatbot-supervisor ;;
  esac
  gid=$(jq -er .id "$TMP_WORK/group-$level.json")
  printf '[]' > "$TMP_WORK/entities.json"
  for uid in $(jq -r '.[]' "$TMP_WORK/active-$level.json"); do
    name="chatbot-human-$uid"
    vault write "identity/entity/name/$name" external_id="$uid" policies='' >/dev/null
    entity=$(vault read -field=id "identity/entity/name/$name")
    alias=$(vault read -format=json "identity/entity/id/$entity" | jq -r --arg name "$name" '[.data.aliases[]?|select(.name==$name)|.id] | if length>1 then error("Alias duplicado") else .[0]//empty end')
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
if vault kv metadata get -mount=secrets chatbot/personal-spaces >/dev/null 2>&1; then
  bash "$(dirname "$0")/configure-personal-spaces.sh"
fi
echo 'Restart Lumen to load the group ID mapping; users must obtain fresh OIDC sessions after changes.'
if vault kv metadata get -mount=secrets chatbot/contracts >/dev/null 2>&1; then
  bash "$(dirname "$0")/configure-contracts.sh"
fi
