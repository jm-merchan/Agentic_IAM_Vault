#!/usr/bin/env bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$(dirname "$0")/configure-personal-spaces.py"
