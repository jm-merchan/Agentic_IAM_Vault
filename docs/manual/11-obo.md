# 11 · Seguir OIDC, OBO y RAR desde Bash

[Índice](README.md) · Requiere [03](03-verify.md), [04](04-vault-iam.md), [02](02-mysql.md) y [05](05-proteccion.md)

Esta prueba reproduce el protocolo sin pedir al LLM que lo haga. El usuario inicia sesión en el navegador; Bash recibe el código, usa PKCE y solicita el token delegado. **No se habilita ROPC** ni se intercambia la contraseña humana por un token desde curl.

El [notebook 10 · tokens con oauth2c](../../10_OAuth2c_Verify_Vault.ipynb) ofrece un recorrido alternativo con la herramienta utilizada por HashiCorp: actor Client Credentials, humano PKCE y token exchange con el STS y RAR. Carga el entorno en cada celda y obtiene credenciales administrativas nuevas para preparar/retirar su callback. Usa este recorrido o el notebook por separado: ambos emplean el puerto 9876.

Para el ensayo completamente por script, [13](13-repeticion-script.md) usa el mismo grant Authorization Code + PKCE: curl envía el formulario de login de Cloud Directory, conserva sus cookies, acepta únicamente el consentimiento de `openid profile email` e intercepta el callback registrado de Lumen. El código se canjea por tokens con el verifier y se validan firma y nonce. No necesita el callback temporal 9876 de este capítulo. Se empieza con un cookie jar vacío para cada usuario, sin `prompt=login`; en este tenant, añadir ese parámetro produjo una segunda pantalla de login tras autenticaciones rápidas.

## 1. Añadir un callback local solo para esta prueba


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

Renovar `verify.headers` con el paso 1 del capítulo 03. Se añade temporalmente `http://localhost:9876/callback`; no se sustituye el callback de Lumen.

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

Si ya utilizas ese callback para otro fin, conserva su configuración y no lo retires al final. No ejecutar esta prueba si el puerto 9876 está ocupado.

## 2. Preparar state, PKCE y la recepción del código

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

Abrir la URL mostrada y entrar como `lumen-reader` (Cloud Directory). La página final muestra «OK». Repetir más adelante el procedimiento para writer/supervisor; comprobar que Verify está usando la cuenta correcta.

## 3. Verificar state e intercambiar el código

Ejecutar tras recibir el callback:

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

El código es de un uso y está ligado al verifier. El **access token resultante no es de un uso**. Decodificar los claims sirve para inspeccionar, no para validar su firma:

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

Debe verse el ID del humano, el grupo correspondiente y `may_act.client_id` igual al client ID OIDC. En la aplicación, PyJWT verifica firma y claims; en esta prueba Vault validará el JWT delegado antes de permitir el acceso.

## 4. Obtener un actor token y hacer token exchange

Preparar credenciales STS y una función cuyo cuerpo deja visible el intercambio completo. Cada llamada obtiene un actor nuevo y solicita RAR para una sola ruta/capacidad:

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

El STS puede emitir RAR para una ruta que el usuario no tiene permitida en Vault. La emisión del token **no concede por sí sola ese permiso**: Vault intersecta permisos del humano, techo del actor y RAR.

## 5. Usar el JWT delegado con Vault CLI

```bash
(
  export VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json")
  vault read -format=json database/creds/chatbot-readonly > "$MANUAL/obo-db.json"
)
jq '{lease_id,lease_duration,username:.data.username}' "$MANUAL/obo-db.json"
```

Lector, gestor y supervisor deben recibir credenciales RO si no existe un bloqueo adicional. Para probar que el JWT con RAR RO no sirve para otra ruta, usar **el mismo JWT**:

```bash
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json database/creds/chatbot-readwrite \
  > "$MANUAL/unexpected-rw.json" 2> "$MANUAL/denied-rw.log"; then
  printf 'ERROR: se esperaba denegación por RAR\n' >&2
  exit 1
fi
cat "$MANUAL/denied-rw.log"
```

Debe indicar **403 / permission denied**; un timeout o error de TLS no demuestra autorización correcta.

Para pedir RW con un RAR nuevo y comprobar el perfil:

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

Esperado: lector 403, gestor éxito, supervisor 403. La capability es `read` porque se leen credenciales del motor, aunque esas credenciales SQL permitan escribir.

## 6. Probar los permisos SQL de la credencial emitida

Sin esperar a que caduque el lease de 120 s, construir un archivo MySQL privado y usarlo dentro del pod. La contraseña no aparece en argv:

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

Comprobar el permiso SQL con una transacción que nunca se confirma. Seleccionar `obo-db.json` para RO; repetir con `obo-rw.json` solo si se emitió correctamente para el gestor. Volver a obtener las credenciales si pasaron 120 segundos.

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
  printf 'INSERT autorizado; transacción revertida\n'
else
  [ "$CREDENTIAL" = obo-db.json ]
  rg -q 'INSERT command denied' "$MANUAL/sql-write.log"
  printf 'INSERT denegado por MySQL al usuario RO\n'
fi
```

El error esperado es `INSERT command denied`; una contraseña caducada o una conexión fallida no demuestra el permiso SQL.

## 7. Probar Transit/Transform y el secreto prohibido

Ejemplo con el ciphertext sintético creado en 05. Primero recuperar los datos de prueba con la credencial administrativa de la terminal, después operar con OBO:

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

Debe funcionar solo con supervisor. Comprobar también las dos rutas de Transform:

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

Esperado: ambos devuelven 403 para lector/gestor y ambos coinciden con el valor original para supervisor. El gestor solo tiene las rutas inversas `encrypt`/`encode`. La comprobación de permisos de la interfaz prueba también esas rutas de escritura con datos sintéticos.

Para comprobar las operaciones de guardado, repetir con RAR específico para `encrypt` y `encode`. Solo el gestor debe pasar estas tres operaciones; lector y supervisor deben recibir 403:

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

Estas llamadas crean tokens sintéticos de prueba en Transform, pero no guardan una solicitud en MySQL.

Ninguno de los tres debe poder leer el secreto administrativo, aunque lo solicite en RAR:

```bash
obo_token secrets/data/verify-admin read
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json secrets/data/verify-admin \
  > "$MANUAL/unexpected-admin.json" 2> "$MANUAL/denied-admin.log"; then
  printf 'ERROR: acceso administrativo inesperado\n' >&2
  exit 1
fi
cat "$MANUAL/denied-admin.log"
```

## 8. Acceso autónomo a Tavily

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

No hay subject humano, actor_token ni token exchange STS en esta llamada. Vault aplica la política de `chatbot-research`, que solo permite leer Tavily. El RAR es opcional únicamente para ese registro. La llamada externa de ejemplo (consume cuota) sería:

```bash
jq -jr '"Authorization: Bearer "+.data.data.TAVILY_API_KEY+"\nContent-Type: application/json\n"' \
  "$MANUAL/tavily.json" > "$MANUAL/tavily.headers"
curl --fail --silent --show-error --header "@$MANUAL/tavily.headers" \
  --data '{"query":"autoconsumo solar residencial España","max_results":3,"search_depth":"basic"}' \
  https://api.tavily.com/search > "$MANUAL/tavily-result.json"
jq '[.results[]|{title,url}]' "$MANUAL/tavily-result.json"
```

## 9. Revocar leases de prueba y retirar el callback temporal

Hacerlo con el token administrativo de la terminal. Si los leases ya caducaron, comprobar su ausencia con `vault lease lookup` y no confundirlo con una revocación fallida del recurso externo.

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

Los JWT Verify conservan su vigencia hasta expirar; `vault token revoke` no revoca JWT externos. Para bloquear accesos anteriores y nuevos ver [12](12-bloqueos.md). Los archivos privados de la sesión manual contienen tokens de corta vida: no incluirlos en Git, README ni capturas públicas.
