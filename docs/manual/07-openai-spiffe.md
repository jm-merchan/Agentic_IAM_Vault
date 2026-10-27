# 07 · OpenAI con SPIFFE JWT-SVID emitido por Vault

[Índice](README.md) · Requiere [04](04-vault-iam.md) · Continúa con [Claude](08-claude-spiffe.md); el selector requiere las tres integraciones

## 1. Definir issuer, identidad y audiencia


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
: "${NGROK_DOMAIN:?Falta el dominio ngrok de tu cuenta}"
export SPIFFE_TRUST_DOMAIN="${SPIFFE_TRUST_DOMAIN:-lumen.demo}"
export SPIFFE_ISSUER="https://$NGROK_DOMAIN/v1/verify/spiffe"
export SPIFFE_SUBJECT="spiffe://$SPIFFE_TRUST_DOMAIN/ns/verify/agent/lumen-openai"
export OPENAI_AUDIENCE=https://api.openai.com/v1
```

El dominio no incluye `https://` en `.env`. `SPIFFE_TRUST_DOMAIN` y el issuer HTTPS son conceptos distintos. Esta demo usa Vault como emisor; no instala SPIRE ni realiza su atestación de nodos/procesos. El workload se autentica primero ante Vault mediante Verify + Agent Registry + RAR.

## 2. Configurar el motor SPIFFE y el rol

Si ya existe `spiffe/`, omitir su habilitación:

```bash
vault secrets enable -path=spiffe spiffe
jq -n --arg domain "$SPIFFE_TRUST_DOMAIN" --arg issuer "$SPIFFE_ISSUER" '{
  trust_domain:$domain,jwt_issuer_url:$issuer,jwt_oidc_compatibility_mode:true,
  jwt_signing_algorithm:"RS256",key_lifetime:"24h",bundle_refresh_hint:"1h"
}' | vault write spiffe/config -
jq -n --arg sub "$SPIFFE_SUBJECT" '{
  template:({sub:$sub,application:"lumen",environment:"demo"}|tojson),ttl:"5m",use_jti_claim:true
}' | vault write spiffe/role/lumen-openai -
vault read spiffe/config
vault read spiffe/role/lumen-openai
vault read -format=json spiffe/.well-known/openid-configuration | jq '.data'
vault read -format=json spiffe/.well-known/keys | jq '.data|{kids:[.keys[].kid]}'
```

La compatibilidad OIDC añade los elementos necesarios para discovery/issuer. El SVID se emite con `sub`, `aud`, `exp`, `iat`, `iss`, `kid` y `jti`. `jti` no lo convierte en un token de un solo uso. [Motor SPIFFE de Vault](https://developer.hashicorp.com/vault/docs/secrets/spiffe).

## 3. Publicar solamente discovery y JWKS con ngrok

Se sirve un directorio de documentos públicos, separado de los secretos y del bootstrap. No publicar el puerto 8443 ni todo `$LUMEN_STATE_DIR`. Esta variante manual usa Vault CLI también para leer documentos públicos; la salida JSON de la CLI envuelve el documento en `.data`.

```bash
export PUBLIC_DIR="$LUMEN_STATE_DIR/ngrok/public"
mkdir -p "$PUBLIC_DIR/v1/verify/spiffe/.well-known"
cat > "$MANUAL/publish-public.sh" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${PUBLIC_DIR:?}" "${SPIFFE_ISSUER:?}" "${VAULT_ADDR:?}" "${VAULT_CACERT:?}"
export VAULT_NAMESPACE=verify
# La lectura pública no necesita una credencial administrativa.
# Un token ficticio evita que la CLI recupere uno del token helper local.
export VAULT_TOKEN=public-documents-only
directory="$PUBLIC_DIR/v1/verify/spiffe/.well-known"
refresh() {
  vault read -format=json spiffe/.well-known/openid-configuration | jq -e '.data' > "$directory/discovery.next" || return 1
  jq -e --arg issuer "$SPIFFE_ISSUER" '.issuer==$issuer and .jwks_uri==($issuer+"/.well-known/keys")' "$directory/discovery.next" >/dev/null || return 1
  vault read -format=json spiffe/.well-known/keys | jq -e '.data' > "$directory/keys.next" || return 1
  jq -e '.keys|length>0 and all(.[];has("kid") and (has("d") or has("p") or has("q") or has("k")|not))' "$directory/keys.next" >/dev/null || return 1
  mv "$directory/discovery.next" "$directory/openid-configuration" || return 1
  mv "$directory/keys.next" "$directory/keys" || return 1
}
while :; do
  if ! refresh; then
    for file in openid-configuration keys discovery.next keys.next; do
      [ ! -f "$directory/$file" ] || rm -- "$directory/$file"
    done
    printf 'Documentos públicos no disponibles; reintento en 30 s.\n' >&2
  fi
  sleep 30
done
BASH
bash "$MANUAL/publish-public.sh" > "$MANUAL/publisher.log" 2>&1 &
PUBLISHER_PID=$!
printf '%s\n' "$PUBLISHER_PID" > "$MANUAL/publisher.pid"
```

Mantener la terminal del publicador abierta. Para ngrok, ejecutar en otra terminal con las variables de [00](00-entorno.md):

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
ngrok_args=(--inspect=false)
if [ -n "${NGROK_AUTHTOKEN:-}" ]; then
  jq -n '{version:"3",agent:{authtoken:env.NGROK_AUTHTOKEN,web_addr:"127.0.0.1:4041"}}' > "$MANUAL/ngrok-agent.json"
  ngrok_args+=(--config "$MANUAL/ngrok-agent.json")
else
  ngrok config check
fi
ngrok http "file://$LUMEN_STATE_DIR/ngrok/public" --url "https://$NGROK_DOMAIN" \
  "${ngrok_args[@]}"
```

El array de argumentos siempre contiene `--inspect=false`: así también funciona con Bash 3.2 de macOS y `set -u` cuando el authtoken ya está configurado y no hay `--config` adicional.

Comprobar desde la terminal principal que la copia pública coincide y que no hay una API de Vault expuesta:

```bash
curl --fail --silent --show-error "$SPIFFE_ISSUER/.well-known/openid-configuration" | \
  jq -e --arg issuer "$SPIFFE_ISSUER" '.issuer==$issuer'
curl --fail --silent --show-error "$SPIFFE_ISSUER/.well-known/keys" | jq -e '.keys|length>0'
for path in /v1/sys/health /ui/ /v1/verify/spiffe/config /v1/verify/secrets/data/openai-admin; do
  code=$(curl --silent --show-error -o /dev/null -w '%{http_code}' "https://$NGROK_DOMAIN$path")
  [ "$code" = 404 ]
done
```

## 4. Crear proyecto y cuenta de servicio por Admin API

En [Admin keys](https://platform.openai.com/settings/organization/admin-keys) crear la credencial administrativa de aprovisionamiento y guardarla en `.env`. No se utiliza para inferencia. Preparar las cabeceras:

```bash
printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$OPENAI_ADMIN_API_KEY" > "$MANUAL/openai-admin.headers"
curl --fail --silent --show-error --header "@$MANUAL/openai-admin.headers" \
  'https://api.openai.com/v1/organization/projects?limit=100' > "$MANUAL/openai-projects.json"
jq '{has_more,last_id,projects:[.data[]|{id,name,status}]}' "$MANUAL/openai-projects.json"
```

Si `has_more=true`, recorrer las páginas añadiendo `&after=<last_id>` antes de decidir que un recurso no existe. Si ya tienes `lumen-vault-demo`, reutilizar su ID y saltar el POST. Para un proyecto nuevo:

```bash
curl --fail --silent --show-error --header "@$MANUAL/openai-admin.headers" \
  --data '{"name":"lumen-vault-demo"}' https://api.openai.com/v1/organization/projects \
  > "$MANUAL/openai-project.json"
export OPENAI_PROJECT_ID=$(jq -er .id "$MANUAL/openai-project.json")
```

Inventariar cuentas de servicio; aplicar el mismo criterio de paginación y reutilización:

```bash
curl --fail --silent --show-error --header "@$MANUAL/openai-admin.headers" \
  "https://api.openai.com/v1/organization/projects/$OPENAI_PROJECT_ID/service_accounts?limit=100" \
  > "$MANUAL/openai-accounts.json"
jq '{has_more,last_id,accounts:[.data[]|{id,name}]}' "$MANUAL/openai-accounts.json"
```

Solo si no existe `lumen-chatbot`, crearla y revocar la clave estática generada como efecto secundario:

```bash
curl --fail --silent --show-error --header "@$MANUAL/openai-admin.headers" \
  --data '{"name":"lumen-chatbot"}' \
  "https://api.openai.com/v1/organization/projects/$OPENAI_PROJECT_ID/service_accounts" \
  > "$MANUAL/openai-account.json"
export OPENAI_SERVICE_ACCOUNT_ID=$(jq -er .id "$MANUAL/openai-account.json")
CREATED_KEY_ID=$(jq -er .api_key.id "$MANUAL/openai-account.json")
curl --fail --silent --show-error --request DELETE --header "@$MANUAL/openai-admin.headers" \
  "https://api.openai.com/v1/organization/projects/$OPENAI_PROJECT_ID/api_keys/$CREATED_KEY_ID" \
  > "$MANUAL/openai-key-deleted.json"
jq -e '.deleted==true' "$MANUAL/openai-key-deleted.json"
rm -- "$MANUAL/openai-account.json"
```

No revocar claves ajenas de un proyecto existente. Guardar `OPENAI_PROJECT_ID` y `OPENAI_SERVICE_ACCOUNT_ID` en `.env`; estos IDs no son secretos.

## 5. Crear el proveedor de confianza y mapping en el portal

La documentación pública consultada describe esta configuración en UI; no se utilizan endpoints internos del dashboard. En [Workload Identity Providers](https://platform.openai.com/settings/organization/security/workload-identity-provider):

1. Crear proveedor `lumen-vault-spiffe`.
2. Issuer: el valor de `SPIFFE_ISSUER`; en la demo, `https://nondemanding-indistinguishably-claude.ngrok-free.dev/v1/verify/spiffe`.
3. Audiencia: `https://api.openai.com/v1`.
4. Usar discovery normal; desactivar JWKS subido y no añadir transformaciones CEL.
5. Crear mapping `lumen-chatbot`, clave **sub**, valor exacto `spiffe://lumen.demo/ns/verify/agent/lumen-openai` (adaptar el trust domain si se cambió).
6. Seleccionar el proyecto `lumen-vault-demo` y la cuenta `lumen-chatbot` del paso anterior.
7. Limitar a **List models → Read** (`api.model.read`) y **Model capabilities → Request** (`api.model.request`); demás categorías None.
8. Copiar el ID del proveedor a `OPENAI_IDENTITY_PROVIDER_ID` en `.env` y recargar esas variables en la terminal.

No se crea la identidad durante el token exchange. La confianza y el mapping deben existir antes. [Guía oficial OpenAI SPIFFE](https://developers.openai.com/api/docs/guides/workload-identity-federation/spiffe). [Captura del mapping de referencia](../runs/20261015-openai-spiffe/screenshots/openai-mapping-created.jpg).

## 6. Crear el cliente Verify y registrar el agente emisor

Renovar las cabeceras administrativas Verify si hace falta ([03](03-verify.md)).

```bash
PROVIDER=openai
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
APP_ID=$(jq -r --arg name "vault-chatbot-$PROVIDER" '[._embedded.applications[]|select(.name==$name)|
  ._links.self.href|split("/")[-1]]|if length>1 then error("Duplicado") else .[0]//empty end' "$MANUAL/apps.json")
if [ -z "$APP_ID" ]; then
  jq --arg name "vault-chatbot-$PROVIDER" --argjson ttl 300 '
    .+{name:$name,description:"Lumen model workload"} |
    .providers.oidc.properties.grantTypes |= with_entries(.value=(if .key=="clientCredentials" then "true" else "false" end)) |
    .providers.oidc.properties.generateRefreshToken="false" |
    .providers.oidc.properties.accessTokenExpiry=$ttl |
    .providers.oidc.token.attributeMappings=[] |
    .providers.oidc.token.accessTokenType="jwt" |
    .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes=true |
    .providers.oidc.properties.additionalConfig.ignoreUnknownAuthDetailTypes=false |
    .providers.oidc.properties.additionalConfig.authDetailTypes=[{type:"vault:path_access"}]
  ' verify/config/oidc-template.json > "$MANUAL/provider-app.json"
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" \
    --data-binary "@$MANUAL/provider-app.json" "$TENANT/v1.0/applications" > "$MANUAL/created.json"
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
    "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
  APP_ID=$(jq -er --arg name "vault-chatbot-$PROVIDER" '._embedded.applications[]|select(.name==$name)|
    ._links.self.href|split("/")[-1]' "$MANUAL/apps.json")
fi
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications/$APP_ID" > "$MANUAL/provider-app-check.json"
jq -e '.providers.oidc.properties.grantTypes.clientCredentials=="true" and
  .providers.oidc.token.accessTokenType=="jwt" and
  .providers.oidc.properties.additionalConfig.restrictAuthDetailTypes==true and
  .providers.oidc.properties.additionalConfig.ignoreUnknownAuthDetailTypes==false and
  any(.providers.oidc.properties.additionalConfig.authDetailTypes[]; .type=="vault:path_access")' \
  "$MANUAL/provider-app-check.json"
jq --arg id "$APP_ID" '{application_id:$id,client_id:.providers.oidc.properties.clientId,
  client_secret:.providers.oidc.properties.clientSecret}' "$MANUAL/provider-app-check.json" | \
  vault kv put -mount=secrets "chatbot/$PROVIDER" -
```

```bash
vault policy write chatbot-openai - <<'HCL'
path "spiffe/role/lumen-openai/mintjwt" {
  capabilities = ["update"]
  required_parameters = ["audience"]
  allowed_parameters = { "audience" = ["https://api.openai.com/v1"] }
}
HCL

cid=$(vault kv get -format=json -mount=secrets chatbot/openai | jq -er .data.data.client_id)
vault write identity/entity/name/chatbot-openai external_id="$cid" policies=chatbot-openai
entity=$(vault read -field=id identity/entity/name/chatbot-openai)
alias_id=$(vault read -format=json "identity/entity/id/$entity" | \
  jq -r '.data.aliases[]?|select(.name=="chatbot-openai")|.id')
if [ -z "$alias_id" ]; then
  vault write identity/entity-alias name=chatbot-openai canonical_id="$entity" \
    issuer="$TENANT/oauth2" external_id="$cid"
fi
jq -n --arg entity "$entity" '{display_name:"chatbot-openai",entity_id:$entity,
  ceiling_policies:["chatbot-openai"],no_default_ceiling_policy:true,
  optional_authorization_details:false,description:"Lumen model workload with mandatory RAR"
}' | vault write agent-registry/register -
vault read agent-registry/registration/display-name/chatbot-openai
```

La ACL permite únicamente `mintjwt` y exige `audience=https://api.openai.com/v1`; un JWT de Verify con RAR no puede seleccionar otra audiencia. El `sub` SPIFFE queda fijado por la plantilla del rol.

## 7. Preparar el perfil OpenAI para el catálogo

```bash
SPIFFE_ISSUER="https://$NGROK_DOMAIN/v1/verify/spiffe"
SPIFFE_SUBJECT="spiffe://${SPIFFE_TRUST_DOMAIN:-lumen.demo}/ns/verify/agent/lumen-openai"
: "${OPENAI_IDENTITY_PROVIDER_ID:?Falta el ID WIF}"
: "${OPENAI_SERVICE_ACCOUNT_ID:?Falta el ID de la cuenta de servicio}"
jq -n --arg model "${LUMEN_OPENAI_MODEL:-gpt-5.6-luna}" \
  --arg provider "$OPENAI_IDENTITY_PROVIDER_ID" --arg account "$OPENAI_SERVICE_ACCOUNT_ID" \
  --arg issuer "$SPIFFE_ISSUER" --arg sub "$SPIFFE_SUBJECT" '{
  provider:"openai",model:$model,credential_source:"vault_spiffe",
  credential_path:"spiffe/role/lumen-openai/mintjwt",auth_flow:"spiffe_jwt_svid",
  identity_provider_id:$provider,service_account_id:$account,issuer:$issuer,
  spiffe_id:$sub,audience:"https://api.openai.com/v1"
}' > "$MANUAL/model-openai.json"
```

## 8. Emitir un JWT-SVID con la identidad del agente

```bash
vault kv get -format=json -mount=secrets chatbot/openai | jq '.data.data' > "$MANUAL/provider-credential.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+
  "\nContent-Type: application/x-www-form-urlencoded\n"' \
  "$MANUAL/provider-credential.json" > "$MANUAL/provider.headers"
jq -n '{grant_type:"client_credentials",scope:"openid profile email",
  authorization_details:([{type:"vault:path_access",path:"spiffe/role/lumen-openai/mintjwt",capabilities:["update"]}]|tojson)}' | form_encode > "$MANUAL/provider.form"
curl --fail --silent --show-error --header "@$MANUAL/provider.headers" \
  --data-binary "@$MANUAL/provider.form" "$TENANT/oauth2/token" > "$MANUAL/openai-jwt.json"
```

```bash
(
  export VAULT_TOKEN=$(jq -er .access_token "$MANUAL/openai-jwt.json")
  vault write -format=json spiffe/role/lumen-openai/mintjwt \
    audience="$OPENAI_AUDIENCE" > "$MANUAL/svid.json"
)
jq -er .data.token "$MANUAL/svid.json" > "$MANUAL/svid.jwt"
```

Aquí `openai-jwt.json` es el JWT **de Verify para acceder a Vault**; `svid.jwt` es el JWT-SVID **emitido por Vault para OpenAI**. Son tokens distintos.

## 9. Intercambiar el SVID e invocar el modelo

```bash
jq -n --rawfile token "$MANUAL/svid.jwt" --arg provider "$OPENAI_IDENTITY_PROVIDER_ID" \
  --arg account "$OPENAI_SERVICE_ACCOUNT_ID" '{
  grant_type:"urn:ietf:params:oauth:grant-type:token-exchange",
  subject_token_type:"urn:ietf:params:oauth:token-type:jwt",
  subject_token:($token|rtrimstr("\n")),identity_provider_id:$provider,service_account_id:$account
}' > "$MANUAL/openai-exchange.json"
curl --fail --silent --show-error --header 'Content-Type: application/json' \
  --data-binary "@$MANUAL/openai-exchange.json" https://auth.openai.com/oauth/token \
  > "$MANUAL/openai-access.json"
jq '{token_type,expires_in,expires_at,scope}' "$MANUAL/openai-access.json"
jq -jer '"Authorization: Bearer "+.access_token+"\nContent-Type: application/json\n"' \
  "$MANUAL/openai-access.json" > "$MANUAL/openai-inference.headers"
jq -n --arg model "${LUMEN_OPENAI_MODEL:-gpt-5.6-luna}" '{model:$model,
  messages:[{role:"user",content:"Responde solo: SPIFFE OK"}],max_tokens:30}' > "$MANUAL/openai-inference.json"
curl --fail --silent --show-error --header "@$MANUAL/openai-inference.headers" \
  --data-binary "@$MANUAL/openai-inference.json" https://api.openai.com/v1/chat/completions \
  > "$MANUAL/openai-result.json"
jq '.choices[0].message.content' "$MANUAL/openai-result.json"
```

La inferencia consume cuota. OpenAI verifica firma, issuer, audiencia y mapping; el token emitido no dura más que el SVID y no hay refresh token. [Contrato de token exchange](https://developers.openai.com/api/reference/workload-identity-federation).

En Lumen, cada ejecución emite e intercambia un SVID nuevo; además se valida localmente con PyJWT antes de enviarlo a OpenAI. Se exigen más de 210 segundos disponibles al comenzar, con ejecución máxima de 180 y margen de 30. Los comandos manuales anteriores muestran el intercambio mínimo; no sustituyen esas validaciones del runtime ni crean spans de aplicación.

Fuentes locales: [spiffe.sh](../../scripts/demo/spiffe.sh), [openai-admin.sh](../../scripts/demo/openai-admin.sh), [configure-openai.sh](../../chatbot/scripts/configure-openai.sh), [spiffe.py](../../chatbot/app/spiffe.py). Trazas del JWT-SVID: [09](09-observabilidad.md).
