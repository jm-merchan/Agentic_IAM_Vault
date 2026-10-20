# 06 · xAI mediante el motor de secretos dinámicos

[Índice](README.md) · Requiere [04](04-vault-iam.md) · Continúa con [OpenAI](07-openai-spiffe.md)

## 1. Registrar el plugin y configurar su Management API key


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
export VAULT_NAMESPACE=''
sha=$("${K[@]}" -n vault exec vault-0 -- cat /vault/plugins/vault-plugin-secrets-xai.sha256 | tr -d '[:space:]')
vault plugin register -sha256="$sha" secret vault-plugin-secrets-xai
export VAULT_NAMESPACE=verify
vault secrets enable -path=xai vault-plugin-secrets-xai
jq -n '{management_api_key:env.XAI_MANAGEMENT_API_KEY}+
  (if (env.XAI_TEAM_ID//"")!="" then {team_id:env.XAI_TEAM_ID} else {} end)' | \
  vault write xai/config -
```

Omitir `enable` si `xai/` ya existe; el catálogo de plugins se administra en root, la configuración en `verify`. El binario y su checksum vienen en la imagen Docker Hub, no se compila Go durante este procedimiento.

## 2. Definir el rol que emite claves

```bash
vault write xai/roles/lumen - <<'JSON'
{
  "acls": ["api-key:model:*", "api-key:endpoint:*"],
  "ttl": "5m",
  "max_ttl": "10m",
  "set_native_expiry": true
}
JSON
vault read xai/roles/lumen
```

Las ACL son dos elementos del array. No escribir una sola cadena separada por comas. Si ya has ajustado el rol, conservar sus ACL/TTL en vez de sustituirlos por estos valores iniciales.

## 3. Crear el cliente Verify del agente

Renovar las cabeceras administrativas según [03, paso 1](03-verify.md). El cliente solo utiliza Client Credentials y exige el tipo RAR configurado:

```bash
PROVIDER=xai
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" \
  "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
APP_ID=$(jq -r --arg name "vault-chatbot-$PROVIDER" '[._embedded.applications[]|select(.name==$name)|
  ._links.self.href|split("/")[-1]]|if length>1 then error("Duplicado") else .[0]//empty end' "$MANUAL/apps.json")
if [ -z "$APP_ID" ]; then
  jq --arg name "vault-chatbot-$PROVIDER" --argjson ttl 600 '
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

## 4. Registrar la identidad y su autorización en Vault

```bash
vault policy write chatbot-xai - <<'HCL'
# Runtime inference only. The application cannot administer xAI or read its management key.
path "xai/creds/lumen" { capabilities = ["read"] }
# Reauthorize cached inference keys through a real Vault read on every run.
path "secrets/data/chatbot/xai-access" { capabilities = ["read"] }
HCL

cid=$(vault kv get -format=json -mount=secrets chatbot/xai | jq -er .data.data.client_id)
vault write identity/entity/name/chatbot-xai external_id="$cid" policies=chatbot-xai,lumen-block-xai
entity=$(vault read -field=id identity/entity/name/chatbot-xai)
alias_id=$(vault read -format=json "identity/entity/id/$entity" | \
  jq -r '.data.aliases[]?|select(.name=="chatbot-xai")|.id')
if [ -z "$alias_id" ]; then
  vault write identity/entity-alias name=chatbot-xai canonical_id="$entity" \
    issuer="$TENANT/oauth2" external_id="$cid"
fi
jq -n --arg entity "$entity" '{display_name:"chatbot-xai",entity_id:$entity,
  ceiling_policies:["chatbot-xai","lumen-block-xai"],no_default_ceiling_policy:true,
  optional_authorization_details:false,description:"Lumen model workload with mandatory RAR"
}' | vault write agent-registry/register -
vault read agent-registry/registration/display-name/chatbot-xai
```

El agente autónomo se limita con sus **políticas de entidad**. Las ceiling policies limitan delegaciones OBO; por eso `lumen-block-xai` se adjunta también a la entidad. El agente no puede leer `secrets/data/xai_mgmt` ni modificar el motor.

Crear el marcador de autorización de caché solo si no existe:

```bash
if ! vault kv metadata get -mount=secrets chatbot/xai-access >/dev/null 2>&1; then
  openssl rand -hex 16 | jq -Rn '{generation:input}' | vault kv put -mount=secrets chatbot/xai-access -
fi
```

Ante un error de lectura distinto de «secreto ausente», resolverlo antes de crear el marcador. La generación cambia al desbloquear xAI para que una app no reutilice una clave revocada.

## 5. Obtener un JWT con RAR y emitir una clave como el agente

El token solicita las dos rutas exactas: autorización de la caché y emisión de credenciales.

```bash
vault kv get -format=json -mount=secrets chatbot/xai | jq '.data.data' > "$MANUAL/provider-credential.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+
  "\nContent-Type: application/x-www-form-urlencoded\n"' \
  "$MANUAL/provider-credential.json" > "$MANUAL/provider.headers"
jq -n '{grant_type:"client_credentials",scope:"openid profile email",
  authorization_details:([{type:"vault:path_access",path:"xai/creds/lumen",capabilities:["read"]},{type:"vault:path_access",path:"secrets/data/chatbot/xai-access",capabilities:["read"]}]|tojson)}' | form_encode > "$MANUAL/provider.form"
curl --fail --silent --show-error --header "@$MANUAL/provider.headers" \
  --data-binary "@$MANUAL/provider.form" "$TENANT/oauth2/token" > "$MANUAL/xai-jwt.json"
```

```bash
(
  export VAULT_TOKEN=$(jq -er .access_token "$MANUAL/xai-jwt.json")
  vault read -format=json secrets/data/chatbot/xai-access > "$MANUAL/xai-access.json"
  vault read -format=json xai/creds/lumen ttl=300 > "$MANUAL/xai-credential.json"
)
jq '{lease_id,lease_duration,renewable,api_key_id:.data.api_key_id}' "$MANUAL/xai-credential.json"
```

**Usar `vault read secrets/data/...` cuando se prueba un JWT con RAR.** `vault kv get` realiza primero una consulta auxiliar a `sys/internal/ui/mounts/secrets`, que no está en el RAR y recibe `RAR_NO_MATCH`. No ampliar el RAR ni las políticas para permitir esa consulta auxiliar: la lectura directa reproduce la llamada de la app.

El subshell evita sustituir el token administrativo de la terminal. Vault valida el JWT y RAR antes de emitir el secreto; no se hace `vault login` ni se cambia el JWT por un token Vault intermedio.

Prueba opcional de inferencia, que consume cuota xAI:

```bash
jq -jr '"Authorization: Bearer "+.data.api_key+"\nContent-Type: application/json\n"' \
  "$MANUAL/xai-credential.json" > "$MANUAL/xai-api.headers"
jq -n --arg model "${LUMEN_XAI_MODEL:-grok-4.3}" '{model:$model,
  messages:[{role:"user",content:"Responde solo: XAI OK"}],max_tokens:30}' > "$MANUAL/xai-request.json"
curl --fail --silent --show-error --header "@$MANUAL/xai-api.headers" \
  --data-binary "@$MANUAL/xai-request.json" https://api.x.ai/v1/chat/completions \
  > "$MANUAL/xai-response.json"
jq '.choices[0].message.content' "$MANUAL/xai-response.json"
vault lease revoke "$(jq -er .lease_id "$MANUAL/xai-credential.json")"
# La retirada puede tardar unos segundos en propagarse a la API de inferencia.
# Solo se repite la comprobación GET; no se vuelve a emitir ni revocar la clave.
revoked=false
for attempt in $(seq 1 16); do
  status=$(curl --silent --show-error --max-time 15 \
    --output "$MANUAL/xai-revoked.json" --write-out '%{http_code}' \
    --header "@$MANUAL/xai-api.headers" https://api.x.ai/v1/models)
  case "$status" in
    401|403) revoked=true; break;;
    400) if jq -e '.error|test("incorrect api key|invalid api key";"i")' "$MANUAL/xai-revoked.json" >/dev/null; then
           revoked=true
         fi
         break;;
    200) [ "$attempt" -eq 16 ] || sleep 2;;
    *) break;;
  esac
done
[ "$revoked" = true ] || { printf 'Revocación no demostrada: HTTP %s\n' "$status" >&2; exit 1; }
printf 'Clave revocada: HTTP %s, comprobación %s\n' "$status" "$attempt"
```

## 6. Preparar el perfil xAI para el catálogo

```bash
jq -n --arg model "${LUMEN_XAI_MODEL:-grok-4.3}" '{
  provider:"xai",model:$model,credential_source:"vault_dynamic",
  credential_path:"xai/creds/lumen",credential_ttl:300,auth_flow:"client_credentials"
}' > "$MANUAL/model-xai.json"
```

Este paso solo genera el perfil local. El capítulo [10](10-aplicacion.md) publica los tres perfiles en una única escritura a Vault. No contiene una API key de inferencia.

El plugin actual **no implementa renovación del lease**. Lumen reautoriza cada ejecución contra `chatbot/xai-access`; reutiliza la clave solo con la misma generación y más de 210 segundos restantes. Si no, pide una clave nueva. Cada ejecución dura como máximo 180 segundos y respeta un margen de 30 segundos. La expiración nativa xAI y la revocación del lease cubren la retirada. No ejecutar `vault lease renew` como sustituto de este mecanismo.

Fuentes: [xai.sh](../../scripts/demo/xai.sh), [configure-xai.sh](../../chatbot/scripts/configure-xai.sh), [services.py](../../chatbot/app/services.py), [bloqueos manuales](12-bloqueos.md).
