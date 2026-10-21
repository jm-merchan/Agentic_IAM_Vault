#!/usr/bin/env bash
# Authorization Code + PKCE through Verify Cloud Directory HTTP forms, without a browser.
set +x
set -euo pipefail
umask 077
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
if [ "${LUMEN_GUIDED:-0}" = 1 ]; then
  source "$ROOT/scripts/demo/common.sh"
  load_inputs
  export MANUAL="$LUMEN_STATE_DIR/manual"
  TENANT="$VERIFY_TENANT"
  form_encode() { jq -jr 'to_entries|map((.key|@uri)+"="+(.value|tostring|@uri))|join("&")'; }
else
  source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
fi
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
ROLE=${1:?reader, writer or supervisor}
case $ROLE in reader|writer|supervisor) ;; *) exit 2;; esac
TASK_AGENT=${2:-legacy}
case $TASK_AGENT in legacy|read|write|reveal) ;; *) echo 'Unknown task agent' >&2; exit 2;; esac
AUTH_WORK="$MANUAL/login-$ROLE"
login_name=$ROLE
if [ "$TASK_AGENT" != legacy ]; then
  login_name="$ROLE-task-$TASK_AGENT"
  AUTH_WORK="$MANUAL/login-$login_name"
fi
mkdir -p "$AUTH_WORK"
chmod 700 "$AUTH_WORK"
rm -f "$AUTH_WORK/cookies" "$AUTH_WORK/tokens.json"
vault kv get -format=json -mount=secrets "chatbot/users/$ROLE" | jq '.data.data' > "$AUTH_WORK/user.json"
if [ "$TASK_AGENT" = legacy ]; then
  vault kv get -format=json -mount=secrets chatbot/oidc | jq '.data.data' > "$AUTH_WORK/client.json"
else
  vault kv get -format=json -mount=secrets chatbot/task-agents | jq -e --arg task "$TASK_AGENT" '.data.data.agents[$task]' > "$AUTH_WORK/client.json"
fi
STATE=$(openssl rand -hex 24)
NONCE=$(openssl rand -hex 24)
printf '%s' "$NONCE" > "$AUTH_WORK/nonce"
VERIFIER=$(openssl rand -hex 32)
CHALLENGE=$(printf '%s' "$VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
CALLBACK=http://localhost:8088/auth/callback
# A fresh cookie jar already requires login. Avoid prompt=login on the resumed
# authorization request: Verify can otherwise ask again after a fast login.
QUERY=$(jq -n --arg cid "$(jq -er .client_id "$AUTH_WORK/client.json")" --arg state "$STATE" --arg challenge "$CHALLENGE" --arg uri "$CALLBACK" --arg nonce "$NONCE" '{nonce:$nonce,client_id:$cid,response_type:"code",redirect_uri:$uri,scope:"openid profile email",state:$state,code_challenge:$challenge,code_challenge_method:"S256"}' | form_encode)
url="$TENANT/oauth2/authorize?$QUERY"
method=GET
login_sent=false
consent_sent=false
callback_url=''
: > "$AUTH_WORK/navigation.log"
for attempt in $(seq 1 20); do
  case "$url" in "$CALLBACK"\?*) callback_url=$url; break;; "$TENANT/"*) ;; *) echo 'Unexpected authentication destination; stopped' >&2; exit 1;; esac
  args=(--silent --show-error --fail --max-time 40 --cookie "$AUTH_WORK/cookies" --cookie-jar "$AUTH_WORK/cookies" --dump-header "$AUTH_WORK/headers" --output "$AUTH_WORK/page.html")
  if [ "$method" = POST ]; then args+=(--header 'Content-Type: application/x-www-form-urlencoded' --data-binary "@$AUTH_WORK/form"); fi
  curl "${args[@]}" "$url"
  cp "$AUTH_WORK/headers" "$AUTH_WORK/headers-$attempt"
  cp "$AUTH_WORK/page.html" "$AUTH_WORK/page-$attempt.html"
  printf '%s %s %s\n' "$method" "${url%%\?*}" "$(head -1 "$AUTH_WORK/headers" | tr -d '\r')" >> "$AUTH_WORK/navigation.log"
  location=$(awk 'tolower($1)=="location:"{sub(/^[^:]*:[[:space:]]*/,"");sub(/\r$/,"");print}' "$AUTH_WORK/headers" | tail -1)
  if [ -n "$location" ]; then
    case "$location" in https://*|http://*) url=$location;; /*) url="$TENANT$location";; *) echo 'Unsupported redirect' >&2; exit 1;; esac
    method=GET
    continue
  fi
  perl "$ROOT/scripts/manual/forms.pl" "$AUTH_WORK/page.html" > "$AUTH_WORK/forms.json"
  if jq -e '.forms[]|select(.fields|has("username") and has("password"))' "$AUTH_WORK/forms.json" > "$AUTH_WORK/selected.json"; then
    [ "$login_sent" = false ] || { echo 'Verify rejected Cloud Directory login; no retry or MFA bypass' >&2; exit 1; }
    url=$(jq -er '.meta.idSourcesMeta|fromjson|.[]|select(.type=="CLOUDDIRECTORY")|.loginUrl' "$AUTH_WORK/forms.json")
    jq --slurpfile u "$AUTH_WORK/user.json" '.fields+{username:$u[0].username,password:$u[0].password}' "$AUTH_WORK/selected.json" | form_encode > "$AUTH_WORK/form"
    login_sent=true
  elif jq -e '.forms[]|select(.action|startswith("/oauth2/consents?"))' "$AUTH_WORK/forms.json" > "$AUTH_WORK/selected.json"; then
    [ "$consent_sent" = false ] || { echo 'Repeated consent; stopped' >&2; exit 1; }
    jq -e '[.fields|to_entries[]|select(.key|test("^dscope[0-9]+$"))|.value]|sort == ["ibm-oauth-scope/email.default#","ibm-oauth-scope/openid.default#","ibm-oauth-scope/profile.default#"]' "$AUTH_WORK/selected.json" >/dev/null
    url="$TENANT$(jq -er .action "$AUTH_WORK/selected.json")"
    jq '.fields+{trust_level:"permit"}' "$AUTH_WORK/selected.json" | form_encode > "$AUTH_WORK/form"
    consent_sent=true
  else
    echo 'Unsupported authentication form or challenge; stopped without bypass' >&2
    exit 1
  fi
  method=POST
done
[ -n "$callback_url" ] || { echo 'No authorization callback received' >&2; exit 1; }
url_decode() { local x=${1//+/ }; [[ "$x" != *\\* ]] || return 1; printf '%b' "${x//%/\\x}"; }
CODE=''; RETURNED_STATE=''; OAUTH_ERROR=''
while IFS='=' read -r k v; do case $k in code) CODE=$(url_decode "$v");;state) RETURNED_STATE=$(url_decode "$v");;error) OAUTH_ERROR=$(url_decode "$v");;esac;done < <(printf '%s\n' "${callback_url#*\?}" | tr '&' '\n')
[ "$RETURNED_STATE" = "$STATE" ] && [ -n "$CODE" ] && [ -z "$OAUTH_ERROR" ]
printf '%s' "$CODE" > "$AUTH_WORK/code"
printf '%s' "$VERIFIER" > "$AUTH_WORK/verifier"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$AUTH_WORK/client.json" > "$AUTH_WORK/token.headers"
jq -n --rawfile code "$AUTH_WORK/code" --rawfile verifier "$AUTH_WORK/verifier" --arg uri "$CALLBACK" '{grant_type:"authorization_code",code:$code,code_verifier:$verifier,redirect_uri:$uri}' | form_encode > "$AUTH_WORK/token.form"
curl --fail --silent --show-error --header "@$AUTH_WORK/token.headers" --data-binary "@$AUTH_WORK/token.form" "$TENANT/oauth2/token" > "$AUTH_WORK/tokens.json"
jq -e '.access_token|type=="string" and length>0' "$AUTH_WORK/tokens.json" > /dev/null
cp "$AUTH_WORK/tokens.json" "$MANUAL/human-$login_name.json"
printf 'OIDC Authorization Code + PKCE: %s OK\n' "$login_name"
