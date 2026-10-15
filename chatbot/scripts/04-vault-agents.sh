#!/usr/bin/env bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
source "$CHATBOT_DIR/scripts/access-controls.sh"
initialize_block_policies
vault read -format=json sys/config/oauth-resource-server/verify > "$TMP_WORK/profile.json"
jq -e '.data.actor_claim=="actor-token.sub" and .data.no_default_policy' "$TMP_WORK/profile.json" >/dev/null
cat > "$TMP_WORK/data-ceiling.hcl" <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
HCL
cat > "$TMP_WORK/writer.hcl" <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
HCL
cat > "$TMP_WORK/supervisor.hcl" <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
HCL
cat > "$TMP_WORK/research.hcl" <<'HCL'
path "secrets/data/tavily" { capabilities = ["read"] }
HCL
cat > "$TMP_WORK/reader.hcl" <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
HCL
vault policy write chatbot-data-ceiling "$TMP_WORK/data-ceiling.hcl" >/dev/null
vault policy write chatbot-reader "$TMP_WORK/reader.hcl" >/dev/null
vault policy write chatbot-writer "$TMP_WORK/writer.hcl" >/dev/null
vault policy write chatbot-supervisor "$TMP_WORK/supervisor.hcl" >/dev/null
vault policy write chatbot-research "$TMP_WORK/research.hcl" >/dev/null
printf '[]' > "$TMP_WORK/agents.json"
for suffix in oidc research; do
  kv_read "chatbot/$suffix" > "$TMP_WORK/client.json"
  cid=$(jq -er .client_id "$TMP_WORK/client.json")
  policy=chatbot-data-ceiling
  optional=false
  [ "$suffix" != research ] || { policy=chatbot-research; optional=true; }
  name="chatbot-$suffix"
  vault write "identity/entity/name/$name" external_id="$cid" policies="$policy" >/dev/null
  entity=$(vault read -field=id "identity/entity/name/$name")
  alias_id=$(vault read -format=json "identity/entity/id/$entity" | jq -r --arg name "$name" '.data.aliases[]?|select(.name==$name)|.id')
  if [ -z "$alias_id" ]; then
    vault write identity/entity-alias name="$name" canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid" >/dev/null
  fi
  jq -n --arg name "$name" --arg entity "$entity" --arg policy "$policy" --argjson optional "$optional" '{display_name:$name,entity_id:$entity,ceiling_policies:([$policy]+(if $name=="chatbot-oidc" then ["lumen-block-database-read","lumen-block-database-write","lumen-block-decrypt"] else [] end)),no_default_ceiling_policy:true,optional_authorization_details:$optional,description:"Lumen chatbot laboratory"}' | vault write agent-registry/register - >/dev/null
  jq --arg name "$name" --arg entity "$entity" --arg cid "$cid" --arg policy "$policy" '.+[{name:$name,entity_id:$entity,client_id:$cid,ceiling_policy:$policy}]' "$TMP_WORK/agents.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/agents.json"
done
vault policy write chatbot-bootstrap "$CHATBOT_DIR/policies/bootstrap.hcl" >/dev/null
if vault kv metadata get -mount=secrets chatbot/xai >/dev/null 2>&1; then
  bash "$CHATBOT_DIR/scripts/register-xai-agent.sh"
fi
if ! vault kv metadata get -mount=secrets chatbot/runtime >/dev/null 2>&1; then
  openssl rand -hex 32 > "$TMP_WORK/session-key"
  jq -n --rawfile key "$TMP_WORK/session-key" '{session_secret:($key|rtrimstr("\n")),groups:{readonly:["chatbot-readers"],readwrite:["chatbot-writers"]}}' | kv_write chatbot/runtime
fi
bash "$CHATBOT_DIR/scripts/configure-permission-probe.sh"
cp "$TMP_WORK/agents.json" "$CHATBOT_DIR/docs/agents.json"
echo 'Two registered agents ready: OBO database and autonomous Tavily. Bootstrap policy has no database/Tavily access.'
