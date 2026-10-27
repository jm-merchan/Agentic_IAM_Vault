#!/usr/bin/env bash
# Optional migration from a running lab. Vault bootstrap is not an .env input.
set +x
set -euo pipefail
umask 077
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
source scripts/demo/env-file.sh "$ROOT"
ENV_FILE=$DEMO_ENV_FILE
if [ -f "$ENV_FILE" ] && rg -q "^VERIFY_ADMIN_CLIENT_SECRET=['\"]?[^'\"[:space:]]" "$ENV_FILE"; then
  echo "$ENV_FILE already contains the integration; it is not overwritten."; exit 0
fi
# A legacy workspace .env is imported into the private location.
TARGET=$LUMEN_STATE_DIR/.env
mkdir -p "$LUMEN_STATE_DIR"
chmod 700 "$LUMEN_STATE_DIR"
source verify/scripts/common.sh
source oracle.env
put() { printf '%s=%q\n' "$1" "$2"; }
OUT=$(mktemp "$LUMEN_STATE_DIR/.env.import.XXXXXX")
trap 'rm -f "$OUT"; rm -rf "$TMP_WORK"' EXIT
{
  if [ -f "$ENV_FILE" ]; then
    # Preserve external inputs, never import generated Vault bootstrap values.
    awk '!/^[[:space:]]*(export[[:space:]]+)?VAULT_(TOKEN|ADDR|CACERT|NAMESPACE)=/' "$ENV_FILE"
    printf '\n'
  fi
  printf '# Entradas privadas del laboratorio. Generado desde sus secretos existentes.\n'
  put VERIFY_TENANT "$TENANT"
  # Assign before put: a failed command substitution in an argument does not stop set -e.
  kv_read verify-admin > "$TMP_WORK/import-admin.json"
  value=$(jq -er .client_id "$TMP_WORK/import-admin.json"); put VERIFY_ADMIN_CLIENT_ID "$value"
  value=$(jq -er .client_secret "$TMP_WORK/import-admin.json"); put VERIFY_ADMIN_CLIENT_SECRET "$value"
  value=$(kv_read xai_mgmt | jq -er .API_KEY); put XAI_MANAGEMENT_API_KEY "$value"
  put XAI_TEAM_ID ''
  value=$(kv_read tavily | jq -er .TAVILY_API_KEY); put TAVILY_API_KEY "$value"
  put ORACLE_REG_EMAIL "$ORACLE_REG_EMAIL"
  put ORACLE_REG_PASSWORD "$ORACLE_REG_PASSWORD"
  value=$(cat vault.hclic); put VAULT_LICENSE "$value"
  value=$(kubectl --context workshop -n mysql exec mysql-enterprise-0 -c mysql -- printenv MYSQL_ROOT_PASSWORD)
  put MYSQL_ROOT_PASSWORD "$value"
  for role in reader writer supervisor; do
    name=$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')
    value=$(kv_read "chatbot/users/$role" | jq -er .password); put "LUMEN_${name}_PASSWORD" "$value"
  done
  unset value
  printf '\n# Configuración no secreta\n'
  # Example defaults only fill keys that the existing .env does not set.
  sed -n '/^MINIKUBE_DRIVER=/,$p' .env.example | awk '
    NR == FNR { if (match($0, /^[A-Za-z_][A-Za-z0-9_]*=/)) seen[substr($0, 1, RLENGTH - 1)] = 1; next }
    !match($0, /^[A-Za-z_][A-Za-z0-9_]*=/) || !(substr($0, 1, RLENGTH - 1) in seen)
  ' "$([ -f "$ENV_FILE" ] && echo "$ENV_FILE" || echo /dev/null)" -
} > "$OUT"
bash -n "$OUT"
chmod 600 "$OUT"
mv "$OUT" "$TARGET"
printf '%s created with the Verify, xAI Management, Tavily, Oracle, license and demo user secrets. Mode 600.\n' "$TARGET"
