# 06 · xAI through the dynamic secrets engine

[Index](README.md) · Requires [04](04-vault-iam.md) · Continues with [OpenAI](07-openai-spiffe.md)

## 1. Register the plugin and configure its Management API key


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
export VAULT_NAMESPACE=''
sha=$("${K[@]}" -n vault exec vault-0 -- cat /vault/plugins/vault-plugin-secrets-xai.sha256 | tr -d '[:space:]')
vault plugin register -sha256="$sha" secret vault-plugin-secrets-xai
export VAULT_NAMESPACE=verify
vault secrets enable -path=xai vault-plugin-secrets-xai
jq -n '{management_api_key:env.XAI_MANAGEMENT_API_KEY}+
  (if (env.XAI_TEAM_ID//"")!="" then {team_id:env.XAI_TEAM_ID} else {} end)' | \
  vault write xai/config -
```

Skip `enable` if `xai/` already exists; the plugin catalog is administered in root, the configuration in `verify`. The binary and its checksum come in the Docker Hub image; no Go is compiled during this procedure.

## 2. Define the role that issues keys

```bash
vault write xai/roles/lumen - <<'JSON'
{
  "acls": ["api-key:model:*", "api-key:endpoint:*"],
  "ttl": "5m",
  "max_ttl": "10m",
  "set_native_expiry": true
}
JSON
vault read xai/roles/lumen
```

The ACLs are two elements of the array. Do not write a single comma-separated string. If you have already adjusted the role, keep its ACLs/TTLs instead of replacing them with these initial values.

## 3. Create the agent's Verify client

Renew the administrative headers as in [03, step 1](03-verify.md). The client only uses Client Credentials and requires the configured RAR type:

```bash
PROVIDER=xai
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
APP_ID=$(jq -r --arg name "vault-chatbot-$PROVIDER" '[._embedded.applications[]|select(.name==$name)|
  ._links.self.href|split("/")[-1]]|if length>1 then error("Duplicate") else .[0]//empty end' "$MANUAL/apps.json")
if [ -z "$APP_ID" ]; then
  jq --arg name "vault-chatbot-$PROVIDER" --argjson ttl 600 '
    .+{name:$name,description:"Lumen model workload"} |
    .providers.oidc.properties.grantTypes |= with_entries(.value=(if .key=="clientCredentials" then "true" else "false" end)) |
    .providers.oidc.properties.generateRefreshToken="false" |
    .providers.oidc.properties.accessTokenExpiry=$ttl |
    .providers.oidc.token.attributeMappings=[] |
    .providers.oidc.token.accessTokenType="jwt" |
    .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes=true |
    .providers.oidc.properties.additionalConfig.ignoreUnknownAuthDetailTypes=false |
    .providers.oidc.properties.additionalConfig.authDetailTypes=[{type:"vault:path_access"}]
  ' verify/config/oidc-template.json > "$MANUAL/provider-app.json"
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" \
    --data-binary "@$MANUAL/provider-app.json" "$TENANT/v1.0/applications" > "$MANUAL/created.json"
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
    "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
  APP_ID=$(jq -er --arg name "vault-chatbot-$PROVIDER" '._embedded.applications[]|select(.name==$name)|
    ._links.self.href|split("/")[-1]' "$MANUAL/apps.json")
fi
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications/$APP_ID" > "$MANUAL/provider-app-check.json"
jq -e '.providers.oidc.properties.grantTypes.clientCredentials=="true" and
  .providers.oidc.token.accessTokenType=="jwt" and
  .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes==true and
  .providers.oidc.properties.additionalConfig.ignoreUnknownAuthDetailTypes==false and
  any(.providers.oidc.properties.additionalConfig.authDetailTypes[]; .type=="vault:path_access")' \
  "$MANUAL/provider-app-check.json"
jq --arg id "$APP_ID" '{application_id:$id,client_id:.providers.oidc.properties.clientId,
  client_secret:.providers.oidc.properties.clientSecret}' "$MANUAL/provider-app-check.json" | \
  vault kv put -mount=secrets "chatbot/$PROVIDER" -
```

## 4. Register the identity and its authorization in Vault

```bash
vault policy write chatbot-xai - <<'HCL'
# Runtime inference only. The application cannot administer xAI or read its management key.
path "xai/creds/lumen" { capabilities = ["read"] }
# Reauthorize cached inference keys through a real Vault read on every run.
path "secrets/data/chatbot/xai-access" { capabilities = ["read"] }
HCL

cid=$(vault kv get -format=json -mount=secrets chatbot/xai | jq -er .data.data.client_id)
vault write identity/entity/name/chatbot-xai external_id="$cid" policies=chatbot-xai,lumen-block-xai
entity=$(vault read -field=id identity/entity/name/chatbot-xai)
alias_id=$(vault read -format=json "identity/entity/id/$entity" | \
  jq -r '.data.aliases[]?|select(.name=="chatbot-xai")|.id')
if [ -z "$alias_id" ]; then
  vault write identity/entity-alias name=chatbot-xai canonical_id="$entity" \
    issuer="$TENANT/oauth2" external_id="$cid"
fi
jq -n --arg entity "$entity" '{display_name:"chatbot-xai",entity_id:$entity,
  ceiling_policies:["chatbot-xai","lumen-block-xai"],no_default_ceiling_policy:true,
  optional_authorization_details:false,description:"Lumen model workload with mandatory RAR"
}' | vault write agent-registry/register -
vault read agent-registry/registration/display-name/chatbot-xai
```

The autonomous agent is limited by its **entity policies**. Ceiling policies limit OBO delegations; that is why `lumen-block-xai` is also attached to the entity. The agent cannot read `secrets/data/xai_mgmt` or modify the engine.

Create the cache authorization marker only if it does not exist:

```bash
if ! vault kv metadata get -mount=secrets chatbot/xai-access >/dev/null 2>&1; then
  openssl rand -hex 16 | jq -Rn '{generation:input}' | vault kv put -mount=secrets chatbot/xai-access -
fi
```

If you get a read error other than "secret not found", resolve it before creating the marker. The generation changes when xAI is unblocked so that an app does not reuse a revoked key.

## 5. Obtain a JWT with RAR and issue a key as the agent

The token requests the two exact paths: cache authorization and credential issuance.

```bash
vault kv get -format=json -mount=secrets chatbot/xai | jq '.data.data' > "$MANUAL/provider-credential.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+
  "\nContent-Type: application/x-www-form-urlencoded\n"' \
  "$MANUAL/provider-credential.json" > "$MANUAL/provider.headers"
jq -n '{grant_type:"client_credentials",scope:"openid profile email",
  authorization_details:([{type:"vault:path_access",path:"xai/creds/lumen",capabilities:["read"]},{type:"vault:path_access",path:"secrets/data/chatbot/xai-access",capabilities:["read"]}]|tojson)}' | form_encode > "$MANUAL/provider.form"
curl --fail --silent --show-error --header "@$MANUAL/provider.headers" \
  --data-binary "@$MANUAL/provider.form" "$TENANT/oauth2/token" > "$MANUAL/xai-jwt.json"
```

```bash
(
  export VAULT_TOKEN=$(jq -er .access_token "$MANUAL/xai-jwt.json")
  vault read -format=json secrets/data/chatbot/xai-access > "$MANUAL/xai-access.json"
  vault read -format=json xai/creds/lumen ttl=300 > "$MANUAL/xai-credential.json"
)
jq '{lease_id,lease_duration,renewable,api_key_id:.data.api_key_id}' "$MANUAL/xai-credential.json"
```

**Use `vault read secrets/data/...` when testing a JWT with RAR.** `vault kv get` first makes an auxiliary query to `sys/internal/ui/mounts/secrets`, which is not in the RAR and receives `RAR_NO_MATCH`. Do not widen the RAR or the policies to allow that auxiliary query: the direct read reproduces the app's call.

The subshell avoids replacing the terminal's administrative token. Vault validates the JWT and RAR before issuing the secret; there is no `vault login` and the JWT is not exchanged for an intermediate Vault token.

Optional inference test, which consumes xAI quota:

```bash
jq -jr '"Authorization: Bearer "+.data.api_key+"\nContent-Type: application/json\n"' \
  "$MANUAL/xai-credential.json" > "$MANUAL/xai-api.headers"
jq -n --arg model "${LUMEN_XAI_MODEL:-grok-4.3}" '{model:$model,
  messages:[{role:"user",content:"Reply only: XAI OK"}],max_tokens:30}' > "$MANUAL/xai-request.json"
curl --fail --silent --show-error --header "@$MANUAL/xai-api.headers" \
  --data-binary "@$MANUAL/xai-request.json" https://api.x.ai/v1/chat/completions \
  > "$MANUAL/xai-response.json"
jq '.choices[0].message.content' "$MANUAL/xai-response.json"
vault lease revoke "$(jq -er .lease_id "$MANUAL/xai-credential.json")"
# The revocation can take a few seconds to propagate to the inference API.
# Only the GET check is repeated; the key is not issued or revoked again.
revoked=false
for attempt in $(seq 1 16); do
  status=$(curl --silent --show-error --max-time 15 \
    --output "$MANUAL/xai-revoked.json" --write-out '%{http_code}' \
    --header "@$MANUAL/xai-api.headers" https://api.x.ai/v1/models)
  case "$status" in
    401|403) revoked=true; break;;
    400) if jq -e '.error|test("incorrect api key|invalid api key";"i")' "$MANUAL/xai-revoked.json" >/dev/null; then
           revoked=true
         fi
         break;;
    200) [ "$attempt" -eq 16 ] || sleep 2;;
    *) break;;
  esac
done
[ "$revoked" = true ] || { printf 'Revocation not demonstrated: HTTP %s\n' "$status" >&2; exit 1; }
printf 'Key revoked: HTTP %s, check %s\n' "$status" "$attempt"
```

<a id="6-preparar-el-perfil-xai-para-el-catálogo"></a>
## 6. Prepare the xAI profile for the catalog

```bash
jq -n --arg model "${LUMEN_XAI_MODEL:-grok-4.3}" '{
  provider:"xai",model:$model,credential_source:"vault_dynamic",
  credential_path:"xai/creds/lumen",credential_ttl:300,auth_flow:"client_credentials"
}' > "$MANUAL/model-xai.json"
```

This step only generates the local profile. Chapter [10](10-aplicacion.md) publishes the three profiles in a single write to Vault. It contains no inference API key.

The current plugin **does not implement lease renewal**. Lumen reauthorizes each run against `chatbot/xai-access`; it reuses the key only with the same generation and more than 210 seconds remaining. Otherwise, it requests a new key. Each run lasts at most 180 seconds and respects a 30-second margin. Native xAI expiry and lease revocation cover the removal. Do not run `vault lease renew` as a substitute for this mechanism.

Sources: [xai.sh](../../scripts/demo/xai.sh), [configure-xai.sh](../../chatbot/scripts/configure-xai.sh), [services.py](../../chatbot/app/services.py), [manual blocks](12-bloqueos.md).
