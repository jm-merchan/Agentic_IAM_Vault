#!/usr/bin/env bash
# Explicit operator command: print only the dedicated demo account credential.
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify
validator=$(vault kv get -format=json -mount=secrets chatbot/contracts | jq -er .data.data.validator_username)
if [ "$validator" != lumen-validator ]; then
  printf 'Validador: %s\nUsa su inicio de sesión habitual en Verify. No se ha creado ni cambiado su contraseña.\n' "$validator"
  exit 0
fi
vault kv get -format=json -mount=secrets chatbot/users/validator | jq -er '"Usuario: " + .data.data.username + "\nContraseña: " + .data.data.password'
