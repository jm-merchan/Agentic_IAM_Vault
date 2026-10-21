#!/usr/bin/env bash
# Sourced after common.sh and admin_login. Reconcile only the known lab schema.
configure_rar() {
  api GET /v1.0/auth-detail-types "$TMP_WORK/rar-list.json"
  RAR_ID=$(jq -er '[..|objects|select(.type?=="vault:path_access")|.id]|unique|
    if length>1 then error("Duplicate RAR type") else .[0]//"" end' "$TMP_WORK/rar-list.json")
  if [ -z "$RAR_ID" ]; then
    jq -n --rawfile schema "$VERIFY_DIR/config/rar-schema.json" '{type:"vault:path_access",
      description:"Vault path, capabilities and parameter restrictions for delegated access",
      schema:$schema,inlineMode:true,
      consentInlineText:("<div>Permitir al agente las operaciones solicitadas en Vault.</div>"|@base64)}' > "$TMP_WORK/rar-create.json"
    api POST /v1.0/auth-detail-types "$TMP_WORK/rar-created.json" --data-binary "@$TMP_WORK/rar-create.json"
    api GET /v1.0/auth-detail-types "$TMP_WORK/rar-list.json"
    RAR_ID=$(jq -er '[..|objects|select(.type?=="vault:path_access")|.id]|unique|
      if length==1 then .[0] else error("RAR duplicated or absent") end' "$TMP_WORK/rar-list.json")
  fi
  api GET "/v1.0/auth-detail-types/$RAR_ID" "$TMP_WORK/rar-check.json"
  if ! jq -e --slurpfile wanted "$VERIFY_DIR/config/rar-schema.json" '(.schema|fromjson)==$wanted[0]' "$TMP_WORK/rar-check.json" >/dev/null; then
    jq -e --slurpfile wanted "$VERIFY_DIR/config/rar-schema.json" '
      (.schema|fromjson)==($wanted[0]|del(.properties.allowed_parameters,.properties.denied_parameters,.properties.required_parameters))
    ' "$TMP_WORK/rar-check.json" >/dev/null || fail 'El esquema RAR no es una versión conocida de Lumen; no se modifica.'
    jq --rawfile schema "$VERIFY_DIR/config/rar-schema.json" '.schema=$schema' "$TMP_WORK/rar-check.json" > "$TMP_WORK/rar-update.json"
    api PUT "/v1.0/auth-detail-types/$RAR_ID" "$TMP_WORK/rar-updated.json" --data-binary "@$TMP_WORK/rar-update.json"
    api GET "/v1.0/auth-detail-types/$RAR_ID" "$TMP_WORK/rar-check.json"
  fi
  jq -e --slurpfile wanted "$VERIFY_DIR/config/rar-schema.json" '(.schema|fromjson)==$wanted[0]' "$TMP_WORK/rar-check.json" >/dev/null || fail 'Verify no conserva el esquema RAR esperado.'
  echo 'RAR preparado: ruta, capacidades y parámetros opcionales; se conserva el ID existente.'
}
