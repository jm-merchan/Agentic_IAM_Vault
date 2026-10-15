#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
[ "$VAULT_ADDR" = 'https://127.0.0.1:8443' ] || fail 'Unexpected Vault address; review the lab target.'
[ -r "$VAULT_CACERT" ] || fail 'Vault CA file is missing.'
vault status -format=json | jq -e '(.sealed==false)' >/dev/null
vault secrets list -format=json | jq -e '."secrets/".type=="kv" and ."secrets/".options.version=="2"' >/dev/null
for secret in verify verify-admin; do
  vault kv metadata get -mount=secrets "$secret" >/dev/null
done
curl --fail --silent --show-error "$TENANT/oauth2/.well-known/openid-configuration" | jq -e --arg issuer "$TENANT/oauth2" '.issuer==$issuer' >/dev/null
printf 'Prerequisites OK: Vault unsealed, namespace verify, KV v2, bootstrap credentials and discovery.\n'
