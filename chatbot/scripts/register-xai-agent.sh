#!/usr/bin/env bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
source "$CHATBOT_DIR/scripts/access-controls.sh"
initialize_block_policies
vault read -format=json sys/config/oauth-resource-server/verify > "$TMP_WORK/profile.json"
jq -e '.data.no_default_policy and .data.user_claim=="sub"' "$TMP_WORK/profile.json" >/dev/null
kv_read chatbot/xai > "$TMP_WORK/client.json"
cid=$(jq -er .client_id "$TMP_WORK/client.json")
vault policy write chatbot-xai "$CHATBOT_DIR/policies/xai.hcl" >/dev/null
vault write identity/entity/name/chatbot-xai external_id="$cid" policies=chatbot-xai,lumen-block-xai >/dev/null
entity=$(vault read -field=id identity/entity/name/chatbot-xai)
alias_id=$(vault read -format=json "identity/entity/id/$entity" | jq -r '.data.aliases[]?|select(.name=="chatbot-xai")|.id')
if [ -z "$alias_id" ]; then
  # After changing the Vault image, Vault can read the stored profile while its
  # issuer lookup is cold. Reapply the same profile before creating a new alias.
  jq '.data|del(.config_id,.profile_name,.mount_accessor)' "$TMP_WORK/profile.json" | vault write sys/config/oauth-resource-server/verify - >/dev/null
  [ "$(vault read -field=config_id sys/config/oauth-resource-server/verify)" = "$(jq -r .data.config_id "$TMP_WORK/profile.json")" ] || fail 'OAuth profile ID changed'
  vault write identity/entity-alias name=chatbot-xai canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid" >/dev/null
fi
jq -n --arg entity "$entity" '{display_name:"chatbot-xai",entity_id:$entity,ceiling_policies:["chatbot-xai","lumen-block-xai"],no_default_ceiling_policy:true,optional_authorization_details:false,description:"Lumen dynamic xAI inference credentials with mandatory RAR"}' | vault write agent-registry/register - > "$TMP_WORK/registration.txt"
vault policy write chatbot-bootstrap "$CHATBOT_DIR/policies/bootstrap.hcl" >/dev/null
jq -n --arg entity "$entity" --arg cid "$cid" '{name:"chatbot-xai",entity_id:$entity,client_id:$cid,ceiling_policy:"chatbot-xai",credential_path:"xai/creds/lumen",auth_flow:"client_credentials"}' > "$CHATBOT_DIR/docs/xai-agent.json"
echo 'Agent chatbot-xai registered: mandatory RAR for xai/creds/lumen and its authorization gate. Bootstrap has no static xAI key access.'
