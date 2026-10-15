#!/usr/bin/env bash
# Sourced by provisioning and the CLI. Policies in Vault are the source of truth.
block_targets() { printf '%s\n' xai database-read database-write decrypt; }
block_paths() {
  case "$1" in
    xai) printf '%s\n' xai/creds/lumen secrets/data/chatbot/xai-access ;;
    database-read) printf '%s\n' database/creds/chatbot-readonly database/creds/chatbot-readwrite ;;
    database-write) printf '%s\n' database/creds/chatbot-readwrite ;;
    decrypt) printf '%s\n' transit/decrypt/lumen-applications transform/decode/lumen-dni transform/decode/lumen-iban ;;
    *) fail 'Recurso inválido: usa xai, database-read, database-write o decrypt.' ;;
  esac
}
initialize_block_policies() {
  local policies target
  policies=$(vault policy list -format=json)
  for target in $(block_targets); do
    if ! jq -e --arg name "lumen-block-$target" 'index($name)!=null' <<< "$policies" >/dev/null; then
      printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write "lumen-block-$target" - >/dev/null
    fi
  done
}
