#!/usr/bin/env bash
# Lumen base: no previous human login or vault-authn-entry instance required.
source "$(dirname "$0")/common.sh"
admin_login
api GET /v1.0/auth-detail-types "$TMP_WORK/rar-list.json"
id=$(jq -r '[..|objects|select(.type?=="vault:path_access")|.id]|unique|if length>1 then error("Duplicate RAR") else .[0]//empty end' "$TMP_WORK/rar-list.json")
if [ -z "$id" ]; then
  jq -n --rawfile schema "$VERIFY_DIR/config/rar-schema.json" '{type:"vault:path_access",description:"Vault path and capabilities for delegated access",schema:$schema,inlineMode:true,consentInlineText:("<div>Permitir al agente las operaciones solicitadas en Vault.</div>"|@base64)}' > "$TMP_WORK/rar.json"
  api POST /v1.0/auth-detail-types "$TMP_WORK/created.json" --data-binary "@$TMP_WORK/rar.json"
  api GET /v1.0/auth-detail-types "$TMP_WORK/rar-list.json"
  id=$(jq -er '[..|objects|select(.type?=="vault:path_access")|.id]|unique|if length==1 then .[0] else error("RAR missing") end' "$TMP_WORK/rar-list.json")
fi
api GET "/v1.0/auth-detail-types/$id" "$TMP_WORK/rar.json"
jq -e --slurpfile schema "$VERIFY_DIR/config/rar-schema.json" '(.schema|fromjson)==$schema[0]' "$TMP_WORK/rar.json" >/dev/null || fail 'El esquema RAR existente difiere del esperado.'
# Match the client's 15-second JWT leeway. Zero rejects freshly issued tokens
# when the IdP clock is a fraction of a second ahead of the VM after resume.
jq -n --arg issuer "$TENANT/oauth2" '{issuer_id:$issuer,jwks_uri:($issuer+"/jwks"),use_jwks:true,user_claim:"sub",actor_claim:"actor-token.sub",supported_algorithms:["RS256"],jwt_type:"access_token",clock_skew_leeway:15,no_default_policy:true,optional_authorization_details:false}' | vault write sys/config/oauth-resource-server/verify - >/dev/null
echo 'RAR y perfil OAuth de Vault preparados; no requieren sesión humana previa.'
