#!/usr/bin/env bash
# Live UI-controller checks with fresh Writer and direct JWTs and disposable leases.
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify LUMEN_GUIDED=1 MANUAL="$LUMEN_STATE_DIR/manual"
export PYTHONPATH="$DEMO_ROOT/chatbot"
export LUMEN_TRACE_VAULT_RAW=0 LUMEN_TRACE_CONTENT=0
export LUMEN_TRACE_DIR="$LUMEN_STATE_DIR/oauth-revocation/lease-traces"
bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" writer write
export CHATBOT_OAUTH_REVOKER_ISSUER
CHATBOT_OAUTH_REVOKER_ISSUER=$(vault read -format=json sys/config/oauth-resource-server/verify | jq -er .data.issuer_id)
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" -c 'import json,os,pathlib; print(pathlib.Path(os.environ["DEMO_ROOT"], "chatbot/policies/oauth-revoker.hcl").read_text().replace("__VERIFY_ISSUER__", json.dumps(os.environ["CHATBOT_OAUTH_REVOKER_ISSUER"])))' | vault policy write chatbot-oauth-revoker - >/dev/null
export CHATBOT_BOOTSTRAP_TOKEN CHATBOT_OAUTH_REVOKER_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m -display-name=lumen-lease-lab-bootstrap | jq -er .auth.client_token)
CHATBOT_OAUTH_REVOKER_TOKEN=$(vault token create -format=json -policy=chatbot-oauth-revoker -no-default-policy -ttl=5m -explicit-max-ttl=5m -display-name=lumen-lease-lab-test | jq -er .auth.client_token)
unset VAULT_TOKEN CHATBOT_OAUTH_REVOKER_ISSUER
unset VERIFY_ADMIN_CLIENT_SECRET XAI_MANAGEMENT_API_KEY XAI_TEAM_ID TAVILY_API_KEY
unset OPENAI_ADMIN_API_KEY OPENAI_API_KEY NGROK_AUTHTOKEN ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE ORACLE_REG_EMAIL ORACLE_REG_PASSWORD
unset VAULT_LICENSE MYSQL_ROOT_PASSWORD LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$DEMO_ROOT/chatbot/scripts/verify-oauth-revocation-leases.py"
