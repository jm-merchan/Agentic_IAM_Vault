#!/usr/bin/env bash
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify
LUMEN_GUIDED=1 bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" writer write
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m -display-name=lumen-contract-verification | jq -er .auth.client_token)
export CHATBOT_BOOTSTRAP_TOKEN PYTHONPATH="$DEMO_ROOT/chatbot"
export LUMEN_TRACE_VAULT_RAW=0 LUMEN_TRACE_CONTENT=0
export LUMEN_TRACE_DIR="$LUMEN_STATE_DIR/contracts/traces"
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$DEMO_ROOT/chatbot/scripts/verify-contracts.py"
