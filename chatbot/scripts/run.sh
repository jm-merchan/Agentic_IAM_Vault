#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
source "${VAULT_ENV_FILE:-/tmp/vault/config.env}"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m -display-name=lumen-bootstrap | jq -er .auth.client_token)
unset VAULT_TOKEN
# Provisioning inputs must never be inherited by the application process.
unset VERIFY_ADMIN_CLIENT_SECRET XAI_MANAGEMENT_API_KEY XAI_TEAM_ID TAVILY_API_KEY
unset OPENAI_ADMIN_API_KEY OPENAI_API_KEY NGROK_AUTHTOKEN
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE
unset ORACLE_REG_EMAIL ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD
unset LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
export LANGSMITH_TRACING=false
export LUMEN_TRACE_CONTENT=${LUMEN_TRACE_CONTENT:-1}
export LUMEN_TRACE_VAULT_RAW=${LUMEN_TRACE_VAULT_RAW:-1}
export LUMEN_TRACE_CONTENT_MAX_BYTES=${LUMEN_TRACE_CONTENT_MAX_BYTES:-65536}
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://127.0.0.1:4318/v1/traces}
export NICEGUI_STORAGE_PATH=${LUMEN_STATE_DIR:-/tmp}/vault-chatbot-storage
mkdir -p "$NICEGUI_STORAGE_PATH"
chmod 700 "$NICEGUI_STORAGE_PATH"
if ! lsof -nP -iTCP:13306 -sTCP:LISTEN >/dev/null 2>&1; then
  kubectl --context workshop -n mysql port-forward --address 127.0.0.1 svc/mysql-enterprise 13306:3306 >/tmp/vault-chatbot-mysql.log 2>&1 &
  FORWARD_PID=$!
  trap 'kill "$FORWARD_PID" 2>/dev/null || true' EXIT
fi
"${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" -m app.main
