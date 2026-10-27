# 11 · Follow OIDC, OBO and RAR from Bash

[Index](README.md) · Requires [03](03-verify.md), [04](04-vault-iam.md), [02](02-mysql.md) and [05](05-proteccion.md)

This test reproduces the protocol without asking the LLM to do it. The user signs in through the browser; Bash receives the code, uses PKCE and requests the delegated token. **ROPC is not enabled**, and the human password is never exchanged for a token from curl.

[Notebook 10 · tokens with oauth2c](../../10_OAuth2c_Verify_Vault.ipynb) offers an alternative walkthrough with the tool used by HashiCorp: Client Credentials actor, PKCE human and token exchange with the STS and RAR. It loads the environment in each cell and obtains fresh administrative credentials to set up/remove its callback. Use either this walkthrough or the notebook, not both at once: they both use port 9876.

For the fully scripted rehearsal, [13](13-repeticion-script.md) uses the same Authorization Code + PKCE grant: curl submits the Cloud Directory login form, keeps its cookies, accepts only the `openid profile email` consent and intercepts Lumen's registered callback. The code is exchanged for tokens with the verifier, and the signature and nonce are validated. It does not need this chapter's temporary 9876 callback. Each user starts with an empty cookie jar, without `prompt=login`; on this tenant, adding that parameter produced a second login screen after quick authentications.

## 1. Add a local callback for this test only


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

Renew `verify.headers` with step 1 of chapter 03. `http://localhost:9876/callback` is added temporarily; Lumen's callback is not replaced.

```bash
vault kv get -format=json -mount=secrets chatbot/oidc | jq '.data.data' > "$MANUAL/oidc-credential.json"
APP_ID=$(jq -er .application_id "$MANUAL/oidc-credential.json")
CLIENT_ID=$(jq -er .client_id "$MANUAL/oidc-credential.json")
export TEST_CALLBACK=http://localhost:9876/callback
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications/$APP_ID" > "$MANUAL/obo-app.json"
jq --arg uri "$TEST_CALLBACK" \
  '.providers.oidc.properties.redirectUris |= ((.+[$uri])|unique)' \
  "$MANUAL/obo-app.json" > "$MANUAL/obo-app-update.json"
curl --fail --silent --show-error --request PUT --header "@$MANUAL/verify.headers" \
  --data-binary "@$MANUAL/obo-app-update.json" "$TENANT/v1.0/applications/$APP_ID" > "$MANUAL/obo-app-result.json"
```

If you already use that callback for another purpose, keep its configuration and do not remove it at the end. Do not run this test if port 9876 is in use.

## 2. Prepare the state, PKCE and the code receiver

```bash
STATE=$(openssl rand -hex 24)
VERIFIER=$(openssl rand -hex 32)
CHALLENGE=$(printf '%s' "$VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
QUERY=$(jq -n --arg cid "$CLIENT_ID" --arg state "$STATE" --arg challenge "$CHALLENGE" \
  --arg uri "$TEST_CALLBACK" '{client_id:$cid,response_type:"code",response_mode:"query",
  redirect_uri:$uri,scope:"openid profile email",state:$state,code_challenge:$challenge,
  code_challenge_method:"S256",prompt:"login"}' | form_encode)
printf 'HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\nContent-Length: 2\r\n\r\nOK' \
  > "$MANUAL/callback-response"
nc -l 127.0.0.1 9876 < "$MANUAL/callback-response" > "$MANUAL/callback-request" 2> "$MANUAL/callback-error.log" &
CALLBACK_PID=$!
printf '%s\n' "$TENANT/oauth2/authorize?$QUERY"
```

Open the URL shown and sign in as `lumen-reader` (Cloud Directory). The final page shows «OK». Repeat the procedure later for writer/supervisor; check that Verify is using the correct account.

## 3. Verify the state and exchange the code

Run after receiving the callback:

```bash
REQUEST=$(head -1 "$MANUAL/callback-request")
[[ "$REQUEST" == 'GET /callback?'* ]]
kill "$CALLBACK_PID" 2>/dev/null || true
wait "$CALLBACK_PID" 2>/dev/null || true
QUERY_RETURNED=${REQUEST#*\?}; QUERY_RETURNED=${QUERY_RETURNED%% HTTP/*}
url_decode() {
  local encoded=${1//+/ }
  [[ "$encoded" != *\\* ]] || return 1
  printf '%b' "${encoded//%/\\x}"
}
CODE=''; RETURNED_STATE=''; OAUTH_ERROR=''
while IFS='=' read -r k v; do
  case "$k" in
    code) CODE=$(url_decode "$v");;
    state) RETURNED_STATE=$(url_decode "$v");;
    error) OAUTH_ERROR=$(url_decode "$v");;
  esac
done < <(printf '%s\n' "$QUERY_RETURNED" | tr '&' '\n')
[ "$RETURNED_STATE" = "$STATE" ]
[ -z "$OAUTH_ERROR" ] && [ -n "$CODE" ]
printf '%s' "$CODE" > "$MANUAL/authorization-code"
printf '%s' "$VERIFIER" > "$MANUAL/pkce-verifier"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+
  "\nContent-Type: application/x-www-form-urlencoded\n"' "$MANUAL/oidc-credential.json" > "$MANUAL/oidc.headers"
jq -n --rawfile code "$MANUAL/authorization-code" --rawfile verifier "$MANUAL/pkce-verifier" \
  --arg uri "$TEST_CALLBACK" '{grant_type:"authorization_code",code:$code,code_verifier:$verifier,redirect_uri:$uri}' | \
  form_encode > "$MANUAL/human.form"
curl --fail --silent --show-error --header "@$MANUAL/oidc.headers" \
  --data-binary "@$MANUAL/human.form" "$TENANT/oauth2/token" > "$MANUAL/human.json"
jq -e '.access_token|type=="string" and length>0' "$MANUAL/human.json"
```

The code is single-use and bound to the verifier. The **resulting access token is not single-use**. Decoding the claims is for inspection, not for validating the signature:

```bash
jwt_claims() {
  local part
  part=$(cut -d. -f2 < "$1" | tr '_-' '/+')
  while [ $((${#part} % 4)) -ne 0 ]; do part="${part}="; done
  printf '%s' "$part" | openssl base64 -d -A | jq -e .
}
jq -er .access_token "$MANUAL/human.json" > "$MANUAL/human.jwt"
jwt_claims "$MANUAL/human.jwt" > "$MANUAL/human-claims.json"
jq '{iss,sub,groups,may_act,exp}' "$MANUAL/human-claims.json"
```

You should see the human's ID, the corresponding group and `may_act.client_id` equal to the OIDC client ID. In the application, PyJWT verifies the signature and claims; in this test, Vault validates the delegated JWT before allowing access.

## 4. Get an actor token and perform the token exchange

Prepare the STS credentials and a function whose body makes the complete exchange visible. Each call obtains a new actor and requests RAR for a single path/capability:

```bash
vault kv get -format=json -mount=secrets chatbot/sts | jq '.data.data' > "$MANUAL/sts-credential.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+
  "\nContent-Type: application/x-www-form-urlencoded\n"' "$MANUAL/sts-credential.json" > "$MANUAL/sts.headers"
obo_token() {
  local resource=$1 capability=$2
  curl --fail --silent --show-error --header "@$MANUAL/oidc.headers" \
    --data 'grant_type=client_credentials&scope=openid%20profile%20email' \
    "$TENANT/oauth2/token" > "$MANUAL/actor.json"
  jq -n --slurpfile human "$MANUAL/human.json" --slurpfile actor "$MANUAL/actor.json" \
    --arg path "$resource" --arg cap "$capability" '{
    grant_type:"urn:ietf:params:oauth:grant-type:token-exchange",
    subject_token:$human[0].access_token,subject_token_type:"urn:ietf:params:oauth:token-type:access_token",
    actor_token:$actor[0].access_token,actor_token_type:"urn:ietf:params:oauth:token-type:access_token",
    requested_token_type:"urn:ietf:params:oauth:token-type:access_token",
    authorization_details:([{type:"vault:path_access",path:$path,capabilities:[$cap]}]|tojson)
  }' | form_encode > "$MANUAL/obo.form"
  curl --fail --silent --show-error --header "@$MANUAL/sts.headers" \
    --data-binary "@$MANUAL/obo.form" "$TENANT/oauth2/token" > "$MANUAL/obo.json"
  jq -e '.access_token|type=="string" and length>0' "$MANUAL/obo.json" >/dev/null
}
obo_token database/creds/chatbot-readonly read
jq -er .access_token "$MANUAL/obo.json" > "$MANUAL/obo.jwt"
jwt_claims "$MANUAL/obo.jwt" | jq '{sub,"actor-token",groups,authorization_details,exp}'
```

The STS can issue RAR for a path the user is not allowed to access in Vault. Issuing the token **does not grant that permission by itself**: Vault intersects the human's permissions, the actor's ceiling and the RAR.

## 5. Use the delegated JWT with the Vault CLI

```bash
(
  export VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json")
  vault read -format=json database/creds/chatbot-readonly > "$MANUAL/obo-db.json"
)
jq '{lease_id,lease_duration,username:.data.username}' "$MANUAL/obo-db.json"
```

Reader, writer and supervisor must receive RO credentials unless an additional block exists. To prove that the JWT with RO RAR does not work for another path, use **the same JWT**:

```bash
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json database/creds/chatbot-readwrite \
  > "$MANUAL/unexpected-rw.json" 2> "$MANUAL/denied-rw.log"; then
  printf 'ERROR: expected denial by RAR\n' >&2
  exit 1
fi
cat "$MANUAL/denied-rw.log"
```

It must show **403 / permission denied**; a timeout or TLS error does not prove that authorization works correctly.

To request RW with a new RAR and check the profile:

```bash
obo_token database/creds/chatbot-readwrite read
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json database/creds/chatbot-readwrite \
  > "$MANUAL/obo-rw.json" 2> "$MANUAL/obo-rw-error.log"; then
  jq '{lease_id,lease_duration,username:.data.username}' "$MANUAL/obo-rw.json"
else
  cat "$MANUAL/obo-rw-error.log"
fi
```

Expected: reader 403, writer success, supervisor 403. The capability is `read` because the engine's credentials are being read, even though those SQL credentials allow writing.

## 6. Test the SQL permissions of the issued credential

Without waiting for the 120 s lease to expire, build a private MySQL file and use it inside the pod. The password does not appear in argv:

```bash
jq -r '"[client]\nuser="+(.data.username|@json)+"\npassword="+(.data.password|@json)' \
  "$MANUAL/obo-db.json" > "$MANUAL/mysql-client.cnf"
"${K[@]}" -n mysql exec -i mysql-enterprise-0 -c mysql -- sh -c '
  umask 077
  cfg=$(mktemp)
  trap '\''rm -- "$cfg"'\'' EXIT
  cat > "$cfg"
  mysql --defaults-extra-file="$cfg" -h 127.0.0.1 --batch scripting \
    -e "SELECT id,name,price_kwh FROM energy_plans"
' < "$MANUAL/mysql-client.cnf"
```

Check the SQL permission with a transaction that is never committed. Select `obo-db.json` for RO; repeat with `obo-rw.json` only if it was issued successfully for the writer. Obtain the credentials again if 120 seconds have passed.

```bash
CREDENTIAL=obo-db.json
jq -r '"[client]\nuser="+(.data.username|@json)+"\npassword="+(.data.password|@json)' \
  "$MANUAL/$CREDENTIAL" > "$MANUAL/mysql-client.cnf"
if "${K[@]}" -n mysql exec -i mysql-enterprise-0 -c mysql -- sh -c '
  umask 077
  cfg=$(mktemp)
  trap '\''rm -- "$cfg"'\'' EXIT
  cat > "$cfg"
  mysql --defaults-extra-file="$cfg" -h 127.0.0.1 --batch scripting \
    -e "START TRANSACTION; INSERT INTO service_requests(subject_id,plan_id,note) VALUES('"'"'manual-test'"'"',1,'"'"'prueba reversible'"'"'); ROLLBACK;"
' < "$MANUAL/mysql-client.cnf" > "$MANUAL/sql-write.log" 2>&1; then
  [ "$CREDENTIAL" = obo-rw.json ]
  printf 'INSERT authorized; transaction rolled back\n'
else
  [ "$CREDENTIAL" = obo-db.json ]
  rg -q 'INSERT command denied' "$MANUAL/sql-write.log"
  printf 'INSERT denied by MySQL to the RO user\n'
fi
```

The expected error is `INSERT command denied`; an expired password or a failed connection does not prove the SQL permission.

## 7. Test Transit/Transform and the forbidden secret

Example with the synthetic ciphertext created in 05. First retrieve the test data with the terminal's administrative credential, then operate with OBO:

```bash
vault kv get -format=json -mount=secrets chatbot/runtime | jq '.data.data.permission_probe' > "$MANUAL/probe.json"
obo_token transit/decrypt/lumen-applications update
jq '{ciphertext:.profile_ciphertext}' "$MANUAL/probe.json" > "$MANUAL/decrypt-request.json"
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault write -format=json transit/decrypt/lumen-applications - \
  < "$MANUAL/decrypt-request.json" > "$MANUAL/obo-decrypt.json" 2> "$MANUAL/obo-decrypt-error.log"; then
  jq -e --slurpfile probe "$MANUAL/probe.json" '.data.plaintext==$probe[0].profile_plaintext' "$MANUAL/obo-decrypt.json"
else
  cat "$MANUAL/obo-decrypt-error.log"
fi
```

It must work only for the supervisor. Also check the two Transform paths:

```bash
for field in dni iban; do
  obo_token "transform/decode/lumen-$field" update
  jq --arg field "$field" '{value:.[$field].token,transformation:("lumen-"+$field)}' \
    "$MANUAL/probe.json" > "$MANUAL/decode-request.json"
  if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
    vault write -format=json "transform/decode/lumen-$field" - \
    < "$MANUAL/decode-request.json" > "$MANUAL/obo-decode-$field.json" 2> "$MANUAL/obo-decode-$field.log"; then
    jq -e --arg field "$field" --slurpfile probe "$MANUAL/probe.json" \
      '.data.decoded_value==$probe[0][$field].value' "$MANUAL/obo-decode-$field.json"
  else
    cat "$MANUAL/obo-decode-$field.log"
  fi
done
```

Expected: both return 403 for reader/writer, and both match the original value for the supervisor. The writer only has the inverse `encrypt`/`encode` paths. The interface's permission check also tests those write paths with synthetic data.

To check the save operations, repeat with a specific RAR for `encrypt` and `encode`. Only the writer must pass these three operations; reader and supervisor must receive 403:

```bash
obo_token transit/encrypt/lumen-applications update
jq '{plaintext:.profile_plaintext}' "$MANUAL/probe.json" > "$MANUAL/encrypt-request.json"
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault write -format=json transit/encrypt/lumen-applications - \
  < "$MANUAL/encrypt-request.json" > "$MANUAL/obo-encrypt.json" 2> "$MANUAL/obo-encrypt.log"; then
  jq -e '.data.ciphertext|startswith("vault:")' "$MANUAL/obo-encrypt.json"
else
  cat "$MANUAL/obo-encrypt.log"
fi
for field in dni iban; do
  obo_token "transform/encode/lumen-$field" update
  jq --arg field "$field" '{value:.[$field].value,transformation:("lumen-"+$field)}' \
    "$MANUAL/probe.json" > "$MANUAL/encode-request.json"
  if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
    vault write -format=json "transform/encode/lumen-$field" - \
    < "$MANUAL/encode-request.json" > "$MANUAL/obo-encode-$field.json" 2> "$MANUAL/obo-encode-$field.log"; then
    jq -e '.data.encoded_value|type=="string" and length>0' "$MANUAL/obo-encode-$field.json"
  else
    cat "$MANUAL/obo-encode-$field.log"
  fi
done
```

These calls create synthetic test tokens in Transform, but they do not save an application in MySQL.

None of the three must be able to read the administrative secret, even if they request it in the RAR:

```bash
obo_token secrets/data/verify-admin read
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json secrets/data/verify-admin \
  > "$MANUAL/unexpected-admin.json" 2> "$MANUAL/denied-admin.log"; then
  printf 'ERROR: unexpected administrative access\n' >&2
  exit 1
fi
cat "$MANUAL/denied-admin.log"
```

## 8. Autonomous access to Tavily

```bash
vault kv get -format=json -mount=secrets chatbot/research | jq '.data.data' > "$MANUAL/research-client.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+
  "\nContent-Type: application/x-www-form-urlencoded\n"' "$MANUAL/research-client.json" > "$MANUAL/research.headers"
curl --fail --silent --show-error --header "@$MANUAL/research.headers" \
  --data 'grant_type=client_credentials&scope=openid%20profile%20email' \
  "$TENANT/oauth2/token" > "$MANUAL/research-jwt.json"
VAULT_TOKEN=$(jq -er .access_token "$MANUAL/research-jwt.json") \
  vault read -format=json secrets/data/tavily > "$MANUAL/tavily.json"
```

There is no human subject, actor_token or STS token exchange in this call. Vault applies the `chatbot-research` policy, which only allows reading Tavily. RAR is optional only for that registration. The example external call (it consumes quota) would be:

```bash
jq -jr '"Authorization: Bearer "+.data.data.TAVILY_API_KEY+"\nContent-Type: application/json\n"' \
  "$MANUAL/tavily.json" > "$MANUAL/tavily.headers"
curl --fail --silent --show-error --header "@$MANUAL/tavily.headers" \
  --data '{"query":"autoconsumo solar residencial España","max_results":3,"search_depth":"basic"}' \
  https://api.tavily.com/search > "$MANUAL/tavily-result.json"
jq '[.results[]|{title,url}]' "$MANUAL/tavily-result.json"
```

## 9. Revoke the test leases and remove the temporary callback

Do this with the terminal's administrative token. If the leases have already expired, check that they are gone with `vault lease lookup` and do not mistake this for a failed revocation of the external resource.

```bash
for file in obo-db.json obo-rw.json; do
  if [ -s "$MANUAL/$file" ]; then
    lease=$(jq -r '.lease_id//empty' "$MANUAL/$file")
    if [ -n "$lease" ]; then vault lease revoke "$lease"; fi
  fi
done
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications/$APP_ID" > "$MANUAL/obo-cleanup.json"
jq --arg uri "$TEST_CALLBACK" '.providers.oidc.properties.redirectUris |= map(select(.!=$uri))' \
  "$MANUAL/obo-cleanup.json" > "$MANUAL/obo-cleanup-update.json"
curl --fail --silent --show-error --request PUT --header "@$MANUAL/verify.headers" \
  --data-binary "@$MANUAL/obo-cleanup-update.json" "$TENANT/v1.0/applications/$APP_ID" \
  > "$MANUAL/obo-cleanup-result.json"
```

Verify JWTs remain valid until they expire; `vault token revoke` does not revoke external JWTs. To block both earlier and new access, see [12](12-bloqueos.md). The private files of the manual session contain short-lived tokens: do not include them in Git, READMEs or public screenshots.
