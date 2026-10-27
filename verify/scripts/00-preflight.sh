#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
[ "$VAULT_ADDR" = 'https://127.0.0.1:8443' ] || fail 'Unexpected Vault address; review the lab target.'
[ -r "$VAULT_CACERT" ] || fail 'Vault CA file is missing.'
vault status -format=json | jq -e '(.sealed==false)' >/dev/null
vault secrets list -format=json | jq -e '."secrets/".type=="kv" and ."secrets/".options.version=="2"' >/dev/null
if ! vault kv metadata get -mount=secrets verify >/dev/null 2>&1; then
  # A recreated Vault loses this copy; read the existing app credential back without rotating it.
  admin_login
  api GET /v1.0/applications "$TMP_WORK/apps.json"
  app_id=$(jq -er '[..|objects|select(.name?=="vault-authn-entry")|._links.self.href|split("/")[-1]]|unique|if length==1 then .[0] else error("Expected exactly one existing vault-authn-entry") end' "$TMP_WORK/apps.json")
  api GET "/v1.0/applications/$app_id" "$TMP_WORK/app.json"
  jq -e '.providers.oidc.properties|{client_id:.clientId,client_secret:.clientSecret}|select(.client_id!=null and .client_secret!=null)' "$TMP_WORK/app.json" | kv_write verify
  printf 'Restored secrets/verify from the existing vault-authn-entry application.\n'
fi
for secret in verify verify-admin; do
  vault kv metadata get -mount=secrets "$secret" >/dev/null
done
curl --fail --silent --show-error "$TENANT/oauth2/.well-known/openid-configuration" | jq -e --arg issuer "$TENANT/oauth2" '.issuer==$issuer' >/dev/null
printf 'Prerequisites OK: Vault unsealed, namespace verify, KV v2, bootstrap credentials and discovery.\n'
