#!/usr/bin/env bash
set +x
set -euo pipefail
source "${VAULT_ENV_FILE:-${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}/vault/config.env}"
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT VAULT_NAMESPACE=''
# Preserve the original device and its HMAC salt, including historical comparisons.
if ! vault audit list -format=json | jq -e 'has("lumen-stdout/")' >/dev/null; then
  vault audit enable -path=lumen-stdout file file_path=stdout log_raw=false hmac_accessor=true >/dev/null
fi
vault write sys/config/auditing/request-headers/traceparent hmac=false >/dev/null
AUDIT_MODE=${LUMEN_VAULT_AUDIT_MODE:-raw}
AGENT_FILTER='namespace == "verify/" and operation == "read" and (path == "database/creds/chatbot-readonly" or path == "database/creds/chatbot-readwrite" or path == "secrets/data/tavily" or path == "secrets/data/verify-admin")'
PROTECTION_FILTER='namespace == "verify/" and (path == "transit/encrypt/lumen-applications" or path == "transit/decrypt/lumen-applications" or path == "transform/encode/lumen-dni" or path == "transform/decode/lumen-dni" or path == "transform/encode/lumen-iban" or path == "transform/decode/lumen-iban")'
XAI_FILTER='namespace == "verify/" and path == "xai/creds/lumen"'
XAI_ACCESS_FILTER='namespace == "verify/" and path == "secrets/data/chatbot/xai-access"'
SPIFFE_FILTER='namespace == "verify/" and (path == "spiffe/role/lumen-openai/mintjwt" or path == "spiffe/role/lumen-anthropic/mintjwt")'
RAW_DEVICES='lumen-spiffe-raw lumen-agent-raw lumen-protection-raw lumen-xai-raw lumen-xai-access-raw'
# A raw device whose filter or options drifted is recreated, never left half-configured.
ensure_raw() {
  local name=$1 description=$2 file_path=$3 filter=$4 healthy='.log_raw=="true" and .hmac_accessor=="false" and .filter==$filter'
  if vault audit list -format=json | jq -e --arg name "$name/" --arg filter "$filter" \
      "has(\$name) and (.[\$name].options | ($healthy) | not)" >/dev/null; then
    vault audit disable "$name" >/dev/null
  fi
  if ! vault audit list -format=json | jq -e --arg name "$name/" 'has($name)' >/dev/null; then
    vault audit enable -path="$name" -description="$description" \
      file file_path="$file_path" mode=0000 log_raw=true hmac_accessor=false filter="$filter" >/dev/null
  fi
  vault audit list -format=json | jq -e --arg name "$name/" --arg filter "$filter" ".[\$name].options | $healthy" >/dev/null
}
case "$AUDIT_MODE" in
  raw)
    ensure_raw lumen-spiffe-raw 'Lumen lab: Vault-issued SPIFFE JWT-SVID for model providers' /proc/self/fd/2 "$SPIFFE_FILTER"
    ensure_raw lumen-agent-raw 'Lumen lab: raw agent routes in verify, including denied admin probe' /dev/stdout "$AGENT_FILTER"
    ensure_raw lumen-protection-raw 'Lumen lab: raw Transit and Transform requests in verify' /dev/stderr "$PROTECTION_FILTER"
    ensure_raw lumen-xai-raw 'Lumen lab: dynamic xAI inference credentials in verify' /proc/self/fd/1 "$XAI_FILTER"
    ensure_raw lumen-xai-access-raw 'Lumen lab: RAR authorization before cached xAI use' /dev/fd/1 "$XAI_ACCESS_FILTER"
    ;;
  hmac)
    for name in $RAW_DEVICES; do
      if vault audit list -format=json | jq -e --arg name "$name/" 'has($name)' >/dev/null; then
        vault audit disable "$name" >/dev/null
      fi
    done
    ;;
  *) echo 'LUMEN_VAULT_AUDIT_MODE must be raw or hmac' >&2; exit 2 ;;
esac
vault audit list -format=json | jq 'with_entries(.value |= {type, options})'
