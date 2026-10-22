#!/usr/bin/env bash
# Additive, idempotent extension. Does not change the existing sign-in clients.
source "$(dirname "$0")/../../verify/scripts/common.sh"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE
export VERIFY_TENANT="$TENANT"
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$(dirname "$0")/configure-contracts.py" "$@"
