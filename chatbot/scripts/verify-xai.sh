#!/usr/bin/env bash
# Live checks with a disposable 60-second key. Never prints JWTs or API keys.
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cleanup() {
  if [ -s "$TMP_WORK/credential.json" ]; then
    lease=$(jq -r '.lease_id//empty' "$TMP_WORK/credential.json")
    if [ -n "$lease" ]; then vault lease revoke "$lease" >/dev/null 2>&1 || true; fi
  fi
  rm -rf "$TMP_WORK"
}
trap cleanup EXIT
printf '[]' > "$TMP_WORK/checks.json"
record() {
  jq --arg name "$1" --argjson passed "$2" '.+[{test:$name,passed:$passed}]' "$TMP_WORK/checks.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/checks.json"
  printf '%s: %s\n' "$1" "$2"
}
kv_read chatbot/xai > "$TMP_WORK/client.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/client.json" > "$TMP_WORK/client.headers"
jq -n '{grant_type:"client_credentials",scope:"openid profile email",authorization_details:([{type:"vault:path_access",path:"xai/creds/lumen",capabilities:["read"]},{type:"vault:path_access",path:"secrets/data/chatbot/xai-access",capabilities:["read"]}]|tojson)}' | form_encode > "$TMP_WORK/form"
http POST "$TENANT/oauth2/token" "$TMP_WORK/oauth.json" "$TMP_WORK/client.headers" --data-binary "@$TMP_WORK/form"
jq -jr '"X-Vault-Token: "+.access_token+"\nX-Vault-Namespace: verify\n"' "$TMP_WORK/oauth.json" > "$TMP_WORK/vault.headers"
http GET "$VAULT_ADDR/v1/xai/creds/lumen?ttl=60" "$TMP_WORK/credential.json" "$TMP_WORK/vault.headers" --cacert "$VAULT_CACERT"
record dynamic_key_issued "$(jq '.lease_duration>0 and .lease_duration<=60 and (.lease_id|startswith("xai/creds/lumen/")) and (.data.api_key|length>0)' "$TMP_WORK/credential.json")"
for path in database/creds/chatbot-readonly secrets/data/tavily secrets/data/xai secrets/data/xai_mgmt xai/config; do
  status=$(curl -sS --max-time 30 --cacert "$VAULT_CACERT" --header "@$TMP_WORK/vault.headers" -o "$TMP_WORK/denied.json" -w '%{http_code}' "$VAULT_ADDR/v1/$path")
  record "xai_agent_denied_$path" "$([ "$status" = 403 ] && echo true || echo false)"
done
vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=2m -explicit-max-ttl=2m > "$TMP_WORK/bootstrap.json"
jq -jr '"X-Vault-Token: "+.auth.client_token+"\nX-Vault-Namespace: verify\n"' "$TMP_WORK/bootstrap.json" > "$TMP_WORK/bootstrap.headers"
for path in secrets/data/xai secrets/data/xai_mgmt xai/creds/lumen; do
  status=$(curl -sS --max-time 30 --cacert "$VAULT_CACERT" --header "@$TMP_WORK/bootstrap.headers" -o "$TMP_WORK/denied.json" -w '%{http_code}' "$VAULT_ADDR/v1/$path")
  record "bootstrap_denied_$path" "$([ "$status" = 403 ] && echo true || echo false)"
done
curl -fsS --max-time 15 --cacert "$VAULT_CACERT" -X POST --header "@$TMP_WORK/bootstrap.headers" "$VAULT_ADDR/v1/auth/token/revoke-self" >/dev/null
kv_read chatbot/model | jq '.providers.xai // .' > "$TMP_WORK/model.json"
jq '{model,messages:[{role:"user",content:"Responde solamente OK."}],max_tokens:128,reasoning_effort:"low"}' "$TMP_WORK/model.json" > "$TMP_WORK/prompt.json"
jq -jr '"Authorization: Bearer "+.data.api_key+"\nContent-Type: application/json\n"' "$TMP_WORK/credential.json" > "$TMP_WORK/xai.headers"
http POST https://api.x.ai/v1/chat/completions "$TMP_WORK/answer.json" "$TMP_WORK/xai.headers" --data-binary "@$TMP_WORK/prompt.json"
record grok_inference_with_dynamic_key "$(jq '(.choices|length)>0' "$TMP_WORK/answer.json")"
echo 'Waiting for the disposable test key to expire (up to 75 seconds).'
for _ in 1 2 3 4 5 6 7; do sleep 10; done
sleep 5
status=$(curl -sS --max-time 30 -X POST --header "@$TMP_WORK/xai.headers" --data-binary "@$TMP_WORK/prompt.json" -o "$TMP_WORK/expired.json" -w '%{http_code}' https://api.x.ai/v1/chat/completions)
# xAI can report invalid keys as HTTP 400. Accept only an explicit key/auth error,
# not an arbitrary malformed request, rate limit or server failure.
auth_error=$(jq -r '((if (.error|type)=="object" then .error.message else .error end) // .message // "" | tostring) as $e | ($e|test("api.?key|authentication";"i")) and ($e|test("incorrect|invalid|expired|deleted|not found|does not exist";"i"))' "$TMP_WORK/expired.json")
record expired_key_rejected_by_xai "$([ "$status" = 401 ] || [ "$status" = 403 ] || { [ "$status" = 400 ] && [ "$auth_error" = true ]; } && echo true || echo false)"
lease=$(jq -er .lease_id "$TMP_WORK/credential.json")
if vault lease lookup -format=json "$lease" > "$TMP_WORK/lease.json" 2>/dev/null; then record expired_lease_removed false; else record expired_lease_removed true; fi
jq -n --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --slurpfile checks "$TMP_WORK/checks.json" --argjson status "$status" '{checked_at:$at,auth_flow:"client_credentials",credential_path:"verify/xai/creds/lumen",test_ttl_seconds:60,expired_xai_http_status:$status,tests:$checks[0],all_passed:([$checks[0][].passed]|all)}' > "$CHATBOT_DIR/docs/xai-dynamic-verification.json"
jq -e .all_passed "$CHATBOT_DIR/docs/xai-dynamic-verification.json" >/dev/null
