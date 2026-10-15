#!/usr/bin/env bash
# Optional migration from a running lab. Vault bootstrap is not an .env input.
set +x
set -euo pipefail
umask 077
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
if [ -f .env ] && rg -q '^VERIFY_ADMIN_CLIENT_SECRET=' .env; then
  echo '.env ya contiene la integración; no se sobrescribe.'; exit 0
fi
source verify/scripts/common.sh
source oracle.env
put() { printf '%s=%q\n' "$1" "$2"; }
OUT=$(mktemp "$ROOT/.env.import.XXXXXX")
trap 'rm -f "$OUT"; rm -rf "$TMP_WORK"' EXIT
{
  if [ -f .env ]; then
    # Preserve external inputs, never import generated Vault bootstrap values.
    awk '!/^[[:space:]]*(export[[:space:]]+)?VAULT_(TOKEN|ADDR|CACERT|NAMESPACE)=/' .env
    printf '\n'
  fi
  printf '# Entradas privadas del laboratorio. Generado desde sus secretos existentes.\n'
  put VERIFY_TENANT "$TENANT"
  kv_read verify-admin > "$TMP_WORK/import-admin.json"
  put VERIFY_ADMIN_CLIENT_ID "$(jq -er .client_id "$TMP_WORK/import-admin.json")"
  put VERIFY_ADMIN_CLIENT_SECRET "$(jq -er .client_secret "$TMP_WORK/import-admin.json")"
  put XAI_MANAGEMENT_API_KEY "$(kv_read xai_mgmt | jq -er .API_KEY)"
  put XAI_TEAM_ID ''
  put TAVILY_API_KEY "$(kv_read tavily | jq -er .TAVILY_API_KEY)"
  put ORACLE_REG_EMAIL "$ORACLE_REG_EMAIL"
  put ORACLE_REG_PASSWORD "$ORACLE_REG_PASSWORD"
  put VAULT_LICENSE "$(cat vault.hclic)"
  put MYSQL_ROOT_PASSWORD "$(kubectl --context workshop -n mysql exec mysql-enterprise-0 -c mysql -- printenv MYSQL_ROOT_PASSWORD)"
  for role in reader writer supervisor; do
    name=$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')
    put "LUMEN_${name}_PASSWORD" "$(kv_read "chatbot/users/$role" | jq -er .password)"
  done
  printf '\n# Configuración no secreta\n'
  sed -n '/^MINIKUBE_DRIVER=/,$p' .env.example
} > "$OUT"
bash -n "$OUT"
chmod 600 "$OUT"
mv "$OUT" .env
printf '.env creado con secretos de Verify, xAI Management, Tavily, Oracle, licencia y usuarios de demo. Permisos 600.\n'
