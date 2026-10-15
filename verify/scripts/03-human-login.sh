#!/usr/bin/env bash
# macOS loopback callback, implemented with Bash, nc, curl, jq and OpenSSL.
source "$(dirname "$0")/common.sh"
command -v nc >/dev/null || fail 'nc is required for the loopback callback.'
kv_read verify > "$TMP_WORK/credential.json"
CLIENT_ID=$(jq -r .client_id "$TMP_WORK/credential.json")
STATE=$(openssl rand -hex 24)
VERIFIER=$(openssl rand -hex 32)
CHALLENGE=$(printf '%s' "$VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
QUERY=$(jq -n --arg cid "$CLIENT_ID" --arg state "$STATE" --arg challenge "$CHALLENGE" '{client_id:$cid,response_type:"code",response_mode:"query",redirect_uri:"http://localhost:9876/callback",scope:"openid profile email",state:$state,code_challenge:$challenge,code_challenge_method:"S256"}' | form_encode)
URL="$TENANT/oauth2/authorize?$QUERY"
printf 'HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\nContent-Length: 45\r\n\r\nCallback recibido. Puedes cerrar esta ventana.' > "$TMP_WORK/http-response"
nc -l 127.0.0.1 9876 < "$TMP_WORK/http-response" > "$TMP_WORK/http-request" 2> "$TMP_WORK/nc-error" &
CALLBACK_PID=$!
trap 'kill "$CALLBACK_PID" 2>/dev/null || true; rm -rf "$TMP_WORK"' EXIT
printf 'Abre esta URL en Chrome y completa el inicio de sesión (10 min):\n%s\n' "$URL"
for ((attempt=0; attempt<600; attempt++)); do
  if head -1 "$TMP_WORK/http-request" | grep -q '^GET /callback?'; then break; fi
  kill -0 "$CALLBACK_PID" 2>/dev/null || fail 'Callback listener stopped; check port 9876.'
  sleep 1
done
REQUEST=$(head -1 "$TMP_WORK/http-request")
[[ "$REQUEST" == 'GET /callback?'* ]] || fail 'Timeout waiting for OAuth callback.'
kill "$CALLBACK_PID" 2>/dev/null || true
wait "$CALLBACK_PID" 2>/dev/null || true
QUERY_RETURNED=${REQUEST#*\?}; QUERY_RETURNED=${QUERY_RETURNED%% HTTP/*}
# Parse URL-encoded query without interpreting shell input as code.
url_decode() { local encoded=${1//+/ }; [[ "$encoded" != *\\* ]] || return 1; printf '%b' "${encoded//%/\\x}"; }
CODE=''; RETURNED_STATE=''; OAUTH_ERROR=''
while IFS='=' read -r k v; do
  case "$k" in code) CODE=$(url_decode "$v");; state) RETURNED_STATE=$(url_decode "$v");; error) OAUTH_ERROR=$(url_decode "$v");; esac
done < <(printf '%s' "$QUERY_RETURNED" | tr '&' '\n'; printf '\n')
[ "$RETURNED_STATE" = "$STATE" ] || fail 'OAuth state mismatch; callback rejected.'
[ -z "$OAUTH_ERROR" ] && [ -n "$CODE" ] || fail 'Authorization was not granted.'
printf '%s' "$CODE" > "$TMP_WORK/code"
printf '%s' "$VERIFIER" > "$TMP_WORK/verifier"
jq -n --rawfile code "$TMP_WORK/code" --rawfile verifier "$TMP_WORK/verifier" '{grant_type:"authorization_code",code:$code,code_verifier:$verifier,redirect_uri:"http://localhost:9876/callback"}' | form_encode > "$TMP_WORK/form"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/credential.json" > "$TMP_WORK/basic.headers"
http POST "$TENANT/oauth2/token" "$TMP_WORK/human.json" "$TMP_WORK/basic.headers" --data-binary "@$TMP_WORK/form"
jq -er .access_token "$TMP_WORK/human.json" > "$TMP_WORK/human.jwt"
jwt_payload "$TMP_WORK/human.jwt" > "$TMP_WORK/claims.json"
jq -e --arg issuer "$TENANT/oauth2" --arg cid "$CLIENT_ID" '.iss==$issuer and .exp>now and .may_act.client_id==$cid' "$TMP_WORK/claims.json" >/dev/null || fail 'Unexpected issuer, expiration or may_act in user token.'
# Decoding checks structure only; Vault validates the JWT signature during API access.
cat "$TMP_WORK/human.json" | kv_write verify-human-session
printf 'Human token stored in Vault. JWT is never printed.\n'
