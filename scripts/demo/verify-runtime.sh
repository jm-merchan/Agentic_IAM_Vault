#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
pid=$(port_pid 8088 || true)
[ -n "$pid" ] || fail 'Lumen no está escuchando en 8088'
process_env=$(ps eww -p "$pid" -o command=)
for name in VAULT_TOKEN VERIFY_ADMIN_CLIENT_SECRET XAI_MANAGEMENT_API_KEY OPENAI_ADMIN_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE NGROK_AUTHTOKEN TAVILY_API_KEY ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD; do
  if [[ "$process_env" =~ (^|[[:space:]])${name}= ]]; then
    unset process_env
    fail "El proceso de aplicación heredó $name"
  fi
done
unset process_env
[ "$(stat -f %Lp "$DEMO_ENV_FILE")" = 600 ] || fail '.env debe tener permisos 600'
curl -fsS http://127.0.0.1:8088/health | jq -e '.status=="ok" and .service=="lumen"' >/dev/null
echo 'Runtime activo; .env privado; sin secretos de aprovisionamiento en el entorno del chatbot.'
