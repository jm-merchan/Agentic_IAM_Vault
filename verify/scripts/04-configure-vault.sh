#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
app_token
ACTOR_ID=$(jq -er .sub "$TMP_WORK/actor-claims.json")
kv_read verify-human-session > "$TMP_WORK/human.json"
jq -er .access_token "$TMP_WORK/human.json" > "$TMP_WORK/human.jwt"
jwt_payload "$TMP_WORK/human.jwt" > "$TMP_WORK/human-claims.json"
HUMAN_ID=$(jq -er .sub "$TMP_WORK/human-claims.json")
admin_login
api GET "/v2.0/Users/$HUMAN_ID" "$TMP_WORK/human-directory.json" --header "Accept: application/scim+json"
jq -e --arg id "$HUMAN_ID" '.id==$id' "$TMP_WORK/human-directory.json" >/dev/null
[ "$ACTOR_ID" != "$HUMAN_ID" ] || fail 'Subject and actor must be different identities.'
jq -n --arg iss "$TENANT/oauth2" --arg jwks "$TENANT/oauth2/jwks" '{issuer_id:$iss,jwks_uri:$jwks,use_jwks:true,user_claim:"sub",actor_claim:"actor-token.sub",supported_algorithms:["RS256"],jwt_type:"access_token",clock_skew_leeway:15,no_default_policy:true,optional_authorization_details:false}' | vault write sys/config/oauth-resource-server/verify - >/dev/null
# HashiCorp documents a Verify STS audience limitation; the profile omits audiences.
cat > "$TMP_WORK/agent-policy.hcl" <<'HCL'
path "secrets/data/agentic-demo/shared" { capabilities = ["read"] }
HCL
cat > "$TMP_WORK/human-policy.hcl" <<'HCL'
path "secrets/data/agentic-demo/shared" { capabilities = ["read"] }
path "secrets/data/agentic-demo/human-only" { capabilities = ["read"] }
HCL
vault policy write verify-agent-read "$TMP_WORK/agent-policy.hcl" >/dev/null
vault policy write verify-human-read "$TMP_WORK/human-policy.hcl" >/dev/null
vault write identity/entity/name/verify-human external_id="$HUMAN_ID" policies=verify-human-read >/dev/null
HUMAN_ENTITY=$(vault read -field=id identity/entity/name/verify-human)
vault write identity/entity/name/verify-agent external_id="$ACTOR_ID" policies=verify-agent-read >/dev/null
ACTOR_ENTITY=$(vault read -field=id identity/entity/name/verify-agent)
CONFIG_ID=$(vault read -field=config_id sys/config/oauth-resource-server/verify)
ensure_alias() {
  local entity=$1 external=$2 name=$3 existing
  existing=$(vault read -format=json "identity/entity/id/$entity" | jq -r --arg name "$name" --arg config "$CONFIG_ID" '.data.aliases[]?|select(.name==$name and (.mount_accessor|endswith("_"+$config)))|.id')
  if [ -z "$existing" ]; then
    vault write identity/entity-alias name="$name" canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$external" >/dev/null
  fi
}
ensure_alias "$HUMAN_ENTITY" "$HUMAN_ID" verify-subject
ensure_alias "$ACTOR_ENTITY" "$ACTOR_ID" verify-actor
# Optional RAR only for this agent enables the autonomous client-credentials test.
# OBO with RAR still uses the intersection of subject policy, agent ceiling and RAR.
jq -n --arg id "$ACTOR_ENTITY" '{display_name:"verify-agent",description:"IBM Verify lab autonomous and delegated agent",entity_id:$id,ceiling_policies:["verify-agent-read"],no_default_ceiling_policy:true,optional_authorization_details:true}' | vault write agent-registry/register - >/dev/null
for path in shared human-only; do
  if ! vault kv metadata get -mount=secrets "agentic-demo/$path" >/dev/null 2>&1; then
    vault kv put -mount=secrets "agentic-demo/$path" message="Synthetic Verify demonstration: $path" >/dev/null
  fi
done
jq -n --arg actor "$ACTOR_ID" --arg human "$HUMAN_ID" --arg ae "$ACTOR_ENTITY" --arg he "$HUMAN_ENTITY" '{actor_external_id:$actor,human_external_id:$human,agent_entity_id:$ae,human_entity_id:$he}' | kv_write verify-identities
vault read -format=json sys/config/oauth-resource-server/verify | jq '.data|{profile_name,issuer_id,enabled,use_jwks,no_default_policy,optional_authorization_details}'
echo 'Vault profile, identities, aliases, policies and agent registry configured in verify.'
