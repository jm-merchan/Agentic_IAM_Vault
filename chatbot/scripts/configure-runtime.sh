#!/usr/bin/env bash
# Preserve the session key when resuming or repeating the manual.
source "$(dirname "$0")/../../verify/scripts/common.sh"
vault kv list -format=json -mount=secrets chatbot > "$TMP_WORK/chatbot-keys.json"
if jq -e 'index("runtime")!=null' "$TMP_WORK/chatbot-keys.json" >/dev/null; then
  kv_read chatbot/runtime > "$TMP_WORK/runtime.json"
  jq -e '(.session_secret|type=="string" and length>0) and (.groups|type=="object")' "$TMP_WORK/runtime.json" >/dev/null ||
    fail 'chatbot/runtime existe pero su formato no es válido; no se sustituye su clave de sesión.'
  echo 'Configuración runtime existente conservada.'
else
  openssl rand -hex 32 > "$TMP_WORK/session-key"
  jq -n --rawfile key "$TMP_WORK/session-key" '{
    session_secret:($key|rtrimstr("\n")),
    groups:{readonly:["chatbot-readers"],readwrite:["chatbot-writers"],sensitive:["chatbot-supervisors"]}
  }' > "$TMP_WORK/runtime.json"
  kv_write chatbot/runtime < "$TMP_WORK/runtime.json"
  echo 'Configuración runtime creada.'
fi
