#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
app_token
kv_read verify-human-session > "$TMP_WORK/human.json"
kv_read verify-sts > "$TMP_WORK/sts.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/sts.json" > "$TMP_WORK/sts.headers"
jq -n --slurpfile actor "$TMP_WORK/actor-token.json" --slurpfile human "$TMP_WORK/human.json" '{grant_type:"urn:ietf:params:oauth:grant-type:token-exchange",subject_token:$human[0].access_token,subject_token_type:"urn:ietf:params:oauth:token-type:access_token",actor_token:$actor[0].access_token,actor_token_type:"urn:ietf:params:oauth:token-type:access_token",requested_token_type:"urn:ietf:params:oauth:token-type:access_token",authorization_details:([{type:"vault:path_access",path:"secrets/data/agentic-demo/shared",capabilities:["read"]}]|tojson)}' > "$TMP_WORK/exchange.json"
form_encode < "$TMP_WORK/exchange.json" > "$TMP_WORK/form"
http POST "$TENANT/oauth2/token" "$TMP_WORK/delegated.json" "$TMP_WORK/sts.headers" --data-binary "@$TMP_WORK/form"
jq -er .access_token "$TMP_WORK/delegated.json" > "$TMP_WORK/delegated.jwt"
jwt_payload "$TMP_WORK/delegated.jwt" > "$TMP_WORK/delegated-claims.json"
jq -er .access_token "$TMP_WORK/human.json" > "$TMP_WORK/human.jwt"
jwt_payload "$TMP_WORK/human.jwt" > "$TMP_WORK/human-claims.json"
jq -e --slurpfile human "$TMP_WORK/human-claims.json" --slurpfile actor "$TMP_WORK/actor-claims.json" '.sub==$human[0].sub and .["actor-token"].sub==$actor[0].sub and any(.authorization_details[]; .type=="vault:path_access" and .capabilities==["read"])' "$TMP_WORK/delegated-claims.json" >/dev/null || fail 'Delegated claims do not match subject, actor and requested RAR.'
cat "$TMP_WORK/delegated.json" | kv_write verify-delegated-session
printf '[]' > "$TMP_WORK/results.json"
probe() {
  local label=$1 token_file=$2 method=$3 path=$4 expected=$5 actual
  { printf 'X-Vault-Token: '; tr -d '\n' < "$token_file"; printf '\nX-Vault-Namespace: verify\nContent-Type: application/json\n'; } > "$TMP_WORK/probe.headers"
  local args=()
  if [ "$method" = POST ]; then
    printf '{"data":{"message":"Negative test: this write must be denied"}}' > "$TMP_WORK/write.json"
    args=(--data-binary "@$TMP_WORK/write.json")
  fi
  actual=$(curl --silent --show-error --connect-timeout 10 --max-time 30 --cacert "$VAULT_CACERT" --header "@$TMP_WORK/probe.headers" --request "$method" ${args[@]+"${args[@]}"} --output "$TMP_WORK/probe.json" --write-out '%{http_code}' "$VAULT_ADDR/v1/$path")
  jq --arg label "$label" --arg actual "$actual" --arg expected "$expected" '.+[{test:$label,status:($actual|tonumber),expected:($expected|tonumber),passed:($actual==$expected)}]' "$TMP_WORK/results.json" > "$TMP_WORK/new.json"
  mv "$TMP_WORK/new.json" "$TMP_WORK/results.json"
  printf '%s: HTTP %s (expected %s)\n' "$label" "$actual" "$expected"
  if [ "$actual" != "$expected" ]; then
    # Vault authentication errors contain no token or returned secret data.
    jq '{errors}' "$TMP_WORK/probe.json" >&2
    fail 'Access test failed.'
  fi
}
probe autonomous_read "$TMP_WORK/actor.jwt" GET secrets/data/agentic-demo/shared 200
probe autonomous_write_denied "$TMP_WORK/actor.jwt" POST secrets/data/agentic-demo/shared 403
probe obo_shared_read "$TMP_WORK/delegated.jwt" GET secrets/data/agentic-demo/shared 200
probe obo_write_denied "$TMP_WORK/delegated.jwt" POST secrets/data/agentic-demo/shared 403
probe obo_human_only_denied "$TMP_WORK/delegated.jwt" GET secrets/data/agentic-demo/human-only 403
probe obo_admin_secret_denied "$TMP_WORK/delegated.jwt" GET secrets/data/verify-admin 403
# Isolate ceiling enforcement: RAR and human ACL permit human-only; agent ceiling does not.
jq '.authorization_details=([{type:"vault:path_access",path:"secrets/data/agentic-demo/human-only",capabilities:["read"]}]|tojson)' "$TMP_WORK/exchange.json" | form_encode > "$TMP_WORK/form"
http POST "$TENANT/oauth2/token" "$TMP_WORK/ceiling.json" "$TMP_WORK/sts.headers" --data-binary "@$TMP_WORK/form"
jq -er .access_token "$TMP_WORK/ceiling.json" > "$TMP_WORK/ceiling.jwt"
probe obo_agent_ceiling_denied "$TMP_WORK/ceiling.jwt" GET secrets/data/agentic-demo/human-only 403
# Isolate RAR enforcement: ACLs permit shared/read; this RAR permits only update.
jq '.authorization_details=([{type:"vault:path_access",path:"secrets/data/agentic-demo/shared",capabilities:["update"]}]|tojson)' "$TMP_WORK/exchange.json" | form_encode > "$TMP_WORK/form"
http POST "$TENANT/oauth2/token" "$TMP_WORK/rar-denied.json" "$TMP_WORK/sts.headers" --data-binary "@$TMP_WORK/form"
jq -er .access_token "$TMP_WORK/rar-denied.json" > "$TMP_WORK/rar-denied.jwt"
probe obo_rar_read_denied "$TMP_WORK/rar-denied.jwt" GET secrets/data/agentic-demo/shared 403
jq -n --arg date "$(date -u +%FT%TZ)" --slurpfile results "$TMP_WORK/results.json" '{checked_at:$date,namespace:"verify",token_exchange:true,signature_validated_by_vault:true,tests:$results[0],all_passed:all($results[0][];.passed)}' > "$VERIFY_DIR/docs/api-verification.json"
echo 'Token exchange and all Vault authorization checks passed.'
