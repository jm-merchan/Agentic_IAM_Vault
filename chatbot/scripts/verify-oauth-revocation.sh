#!/usr/bin/env bash
# Revoke only freshly minted lab JWTs, for delegated and direct access.
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
mode=${1:-both}
case "$mode" in delegated|direct|both) ;; *) fail 'Usage: verify-oauth-revocation.sh [delegated|direct|both] [--pause]';; esac
if [ "$#" -gt 0 ]; then shift; fi
export VAULT_NAMESPACE=verify LUMEN_GUIDED=1 MANUAL="$LUMEN_STATE_DIR/manual"
export PYTHONPATH="$DEMO_ROOT/chatbot"
export LUMEN_TRACE_VAULT_RAW=0 LUMEN_TRACE_CONTENT=0
export LUMEN_TRACE_DIR="$LUMEN_STATE_DIR/oauth-revocation/traces"
if [ "$mode" != direct ]; then
  bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" writer write
fi
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap \
  -no-default-policy -ttl=5m -explicit-max-ttl=5m \
  -display-name=lumen-oauth-revocation-lab | jq -er .auth.client_token)
export CHATBOT_BOOTSTRAP_TOKEN
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$DEMO_ROOT/chatbot/scripts/verify-oauth-revocation.py" "$mode" "$@"
