#!/usr/bin/env bash
# Bash 3.2+; no secrets in arguments, logs, or notebook output.
set +x
set -euo pipefail
umask 077
VERIFY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "${VAULT_ENV_FILE:-/tmp/vault/config.env}"
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT
export VAULT_NAMESPACE=verify
TENANT=${VERIFY_TENANT:-https://merchan.verify.ibm.com}
TENANT=${TENANT%/}
for cmd in curl jq vault openssl; do command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 1; }; done
TMP_WORK=$(mktemp -d /tmp/vault-verify.XXXXXX)
trap 'rm -rf "$TMP_WORK"' EXIT
fail() { printf '%s\n' "$*" >&2; exit 1; }
# Sensitive values travel through stdin or protected files, never curl argv.
kv_read() { vault kv get -format=json -mount=secrets "$1" | jq -e '.data.data'; }
kv_write() { vault kv put -mount=secrets "$1" - >/dev/null; }
form_encode() { jq -jr 'to_entries|map((.key|@uri)+"="+(.value|tostring|@uri))|join("&")'; }
http() {
  local method=$1 url=$2 output=$3 headers=$4; shift 4
  local status
  status=$(curl --silent --show-error --connect-timeout 15 --max-time 90 \
    --request "$method" --header "@$headers" --dump-header "$TMP_WORK/response.headers" \
    --output "$output" --write-out '%{http_code}' "$@" "$url") || fail "Network error: $method $url"
  case "$status" in 2??) ;; *)
    printf 'HTTP %s: %s %s\n' "$status" "$method" "$url" >&2
    # Do not dump raw error bodies: some servers echo credentials or tokens.
    fail 'API rejected the request; response kept private for this process.';; esac
}
admin_login() {
  kv_read verify-admin > "$TMP_WORK/admin.json"
  jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/admin.json" > "$TMP_WORK/basic.headers"
  printf 'grant_type=client_credentials' > "$TMP_WORK/form"
  http POST "$TENANT/oauth2/token" "$TMP_WORK/admin-token.json" "$TMP_WORK/basic.headers" --data-binary "@$TMP_WORK/form"
  jq -jer '"Authorization: Bearer "+.access_token+"\nContent-Type: application/json\nAccept: application/json\n"' "$TMP_WORK/admin-token.json" > "$TMP_WORK/admin.headers"
}
api() { local method=$1 path=$2 out=$3; shift 3; http "$method" "$TENANT$path" "$out" "$TMP_WORK/admin.headers" "$@"; }
jwt_payload() {
  local part
  part=$(cut -d. -f2 < "$1" | tr '_-' '/+')
  while [ $((${#part} % 4)) -ne 0 ]; do part="${part}="; done
  printf '%s' "$part" | openssl base64 -d -A | jq -e .
}
app_token() {
  kv_read verify > "$TMP_WORK/app-credential.json"
  jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/app-credential.json" > "$TMP_WORK/app.headers"
  printf 'grant_type=client_credentials&scope=openid%%20profile%%20email' > "$TMP_WORK/form"
  http POST "$TENANT/oauth2/token" "$TMP_WORK/actor-token.json" "$TMP_WORK/app.headers" --data-binary "@$TMP_WORK/form"
  jq -er '.access_token' "$TMP_WORK/actor-token.json" > "$TMP_WORK/actor.jwt"
  jwt_payload "$TMP_WORK/actor.jwt" > "$TMP_WORK/actor-claims.json"
}
