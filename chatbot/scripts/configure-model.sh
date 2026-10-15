#!/usr/bin/env bash
# OpenAI uses Vault SPIFFE. Anthropic remains an optional static-key adapter.
if [ "${1:-}" = openai ]; then
  exec bash "$(dirname "$0")/../../demo.sh" start --provider openai
fi
source "$(dirname "$0")/../../verify/scripts/common.sh"
read -r -p 'Proveedor (openai/anthropic): ' LUMEN_PROVIDER
case "$LUMEN_PROVIDER" in openai|anthropic) ;; *) fail 'Unsupported provider';; esac
if [ "$LUMEN_PROVIDER" = openai ]; then
  exec bash "$(dirname "$0")/../../demo.sh" start --provider openai
fi
read -r -p 'Nombre exacto del modelo: ' LUMEN_MODEL
[ -n "$LUMEN_MODEL" ] || fail 'Model name is required'
read -r -s -p 'API key (oculta): ' LUMEN_API_KEY
printf '\n'
[ -n "$LUMEN_API_KEY" ] || fail 'API key is required'
printf '%s' "$LUMEN_API_KEY" > "$TMP_WORK/model-key"
unset LUMEN_API_KEY
jq -n --arg provider "$LUMEN_PROVIDER" --arg model "$LUMEN_MODEL" --rawfile key "$TMP_WORK/model-key" '{provider:$provider,model:$model,api_key:$key}' | kv_write chatbot/model
printf 'Modelo guardado en verify/secrets/chatbot/model. Reinicia Lumen.\n'
