#!/usr/bin/env bash
# Real model + OIDC/OBO + MySQL checks. Creates in-memory proposals, never stored requests.
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify
export MANUAL="$LUMEN_STATE_DIR/manual"
export LUMEN_ROOT="$DEMO_ROOT"
for role in reader writer; do
  LUMEN_GUIDED=1 bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" "$role"
done
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m | jq -er .auth.client_token)
unset VAULT_TOKEN VERIFY_ADMIN_CLIENT_SECRET OPENAI_ADMIN_API_KEY OPENAI_API_KEY XAI_MANAGEMENT_API_KEY
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN TAVILY_API_KEY ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD
unset LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
export PYTHONPATH="$DEMO_ROOT/chatbot"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
exec /tmp/vault-chatbot-venv/bin/python "$DEMO_ROOT/chatbot/scripts/verify_catalogue.py"
