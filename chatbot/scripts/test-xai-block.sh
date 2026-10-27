#!/usr/bin/env bash
# Live, reversible check. Requires xAI unblocked; revokes lab xAI leases.
source "$(dirname "$0")/../../verify/scripts/common.sh"
ROOT=$(cd "$VERIFY_DIR/.." && pwd)
policy=$(vault policy read lumen-block-xai)
[[ "$policy" != *'"deny"'* ]] || fail 'Unblock xAI before running this test.'
cleanup() {
  local code=$?
  if [ -f "$TMP_WORK/blocked" ]; then bash "$ROOT/demo.sh" unblock xai >/dev/null || code=1; fi
  for file in "$TMP_WORK/initial.json" "$TMP_WORK/restored.json"; do
    if [ -f "$file" ]; then
      lease=$(jq -r '.lease_id//empty' "$file")
      [ -z "$lease" ] || vault lease revoke -sync "$lease" >/dev/null 2>&1 || code=1
    fi
  done
  rm -rf "$TMP_WORK"
  exit "$code"
}
trap cleanup EXIT
kv_read chatbot/xai > "$TMP_WORK/client.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/client.json" > "$TMP_WORK/client.headers"
printf '[]' > "$TMP_WORK/checks.json"
record() {
  jq --arg name "$1" --argjson passed "$2" '.+[{test:$name,passed:$passed}]' "$TMP_WORK/checks.json" > "$TMP_WORK/next"
  mv "$TMP_WORK/next" "$TMP_WORK/checks.json"
  printf '%s: %s\n' "$1" "$2"
  [ "$2" = true ] || fail "Failed: $1"
}
mint() {
  local mode=$1
  jq -n --arg mode "$mode" '{grant_type:"client_credentials",scope:"openid profile email"} +
    (if $mode=="none" then {} else {authorization_details:((if $mode=="wrong" then
      [{type:"vault:path_access",path:"secrets/data/chatbot/xai-access",capabilities:["read"]}] else
      [{type:"vault:path_access",path:"xai/creds/lumen",capabilities:["read"]},{type:"vault:path_access",path:"secrets/data/chatbot/xai-access",capabilities:["read"]}] end)|tojson)} end)' | form_encode > "$TMP_WORK/form"
  http POST "$TENANT/oauth2/token" "$TMP_WORK/$mode-token.json" "$TMP_WORK/client.headers" --data-binary "@$TMP_WORK/form"
  jq -jr '"X-Vault-Token: "+.access_token+"\nX-Vault-Namespace: verify\n"' "$TMP_WORK/$mode-token.json" > "$TMP_WORK/$mode.headers"
}
request() {
  curl -sS --max-time 40 --cacert "$VAULT_CACERT" --header "@$TMP_WORK/$1.headers" \
    -o "$TMP_WORK/$3.json" -w '%{http_code}' "$VAULT_ADDR/v1/$2"
}
mint none
code=$(request none 'xai/creds/lumen?ttl=60' denied)
record missing_rar_denied "$([ "$code" = 403 ] && echo true || echo false)"
mint wrong
code=$(request wrong 'xai/creds/lumen?ttl=60' denied)
record wrong_rar_denied "$([ "$code" = 403 ] && echo true || echo false)"
mint before
code=$(request before 'xai/creds/lumen?ttl=60' initial)
record allowed_before_block "$([ "$code" = 200 ] && echo true || echo false)"
touch "$TMP_WORK/blocked"
bash "$ROOT/demo.sh" block xai >/dev/null
code=$(request before 'xai/creds/lumen?ttl=60' denied)
record same_jwt_denied_after_block "$([ "$code" = 403 ] && echo true || echo false)"
code=$(request before secrets/data/chatbot/xai-access denied)
record cache_authorization_denied "$([ "$code" = 403 ] && echo true || echo false)"
mint after
code=$(request after 'xai/creds/lumen?ttl=60' denied)
record fresh_jwt_denied_after_block "$([ "$code" = 403 ] && echo true || echo false)"
lease=$(jq -er .lease_id "$TMP_WORK/initial.json")
if vault lease lookup "$lease" >/dev/null 2>&1; then record issued_lease_revoked false; else record issued_lease_revoked true; fi
bash "$ROOT/demo.sh" unblock xai >/dev/null
code=$(request before 'xai/creds/lumen?ttl=60' restored)
record same_jwt_allowed_after_unblock "$([ "$code" = 200 ] && echo true || echo false)"
jq -n --arg at "$(date -u +%FT%TZ)" --slurpfile checks "$TMP_WORK/checks.json" '{checked_at:$at,tests:$checks[0],all_passed:all($checks[0][];.passed)}' > "$ROOT/chatbot/docs/xai-rar-block-verification.json"
