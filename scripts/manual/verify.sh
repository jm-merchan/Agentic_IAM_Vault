#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
source "$MANUAL/session.sh"
# Fresh JWTs require a synchronized clock even when install and verify are separate.
step 01-vault 1
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
# Check all providers regardless of the initial UI preference. Claude's
# inline JWKS must already have been updated after the fresh Vault install.
for n in 1 8 9 10 11 12 13 14; do step 08-claude-spiffe "$n"; done
for n in 1 2 14 15 16; do step 07-openai-spiffe "$n"; done
curl -fsS http://localhost:8088/health | jq -e '.status=="ok" and ([.models[].provider]|sort)==["anthropic","openai","xai"]' >/dev/null
for role in reader writer supervisor; do bash scripts/manual/oidc-login.sh "$role"; done
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m | jq -er .auth.client_token)
unset VAULT_TOKEN VERIFY_ADMIN_CLIENT_SECRET XAI_MANAGEMENT_API_KEY OPENAI_ADMIN_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE TAVILY_API_KEY NGROK_AUTHTOKEN
unset ORACLE_REG_EMAIL ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD
unset LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
export LUMEN_TRACE_CONTENT=1 LUMEN_TRACE_VAULT_RAW=1 OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
export PYTHONPATH="$MANUAL_ROOT/chatbot"
/tmp/vault-chatbot-venv/bin/python "$MANUAL_ROOT/scripts/manual/workflows.py"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
vault kv get -format=json -mount=secrets chatbot/directory | \
 jq '.data.data|{users:[.users[]|{username,user_id,group,group_id,password_reset_required}]}' > "$MANUAL_RUN/users.json"
: > "$MANUAL/agent-inventory.jsonl"
for name in oidc research xai openai anthropic; do
 if vault kv metadata get -mount=secrets "chatbot/$name" >/dev/null 2>&1; then
  vault read -format=json "agent-registry/registration/display-name/chatbot-$name" | \
   jq '.data|{display_name,id,entity_id,ceiling_policies,optional_authorization_details}' >> "$MANUAL/agent-inventory.jsonl"
 fi
done
jq -s . "$MANUAL/agent-inventory.jsonl" > "$MANUAL_RUN/agents.json"
for target in xai database-read database-write decrypt; do
 vault policy read "lumen-block-$target" > "$MANUAL/check-block.hcl"
 status=0; grep -q '"deny"' "$MANUAL/check-block.hcl" || status=$?
 if [ "$status" -eq 0 ]; then echo "Bloqueo inesperado activo: $target" >&2;exit 1;fi
 [ "$status" -eq 1 ] || { echo "No se pudo comprobar el bloqueo: $target" >&2;exit 1; }
done
printf '{"all_blocks_inactive":true}\n' > "$MANUAL_RUN/final-state.json"
