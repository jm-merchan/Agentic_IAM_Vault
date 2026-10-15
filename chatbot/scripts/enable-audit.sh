#!/usr/bin/env bash
set +x
set -euo pipefail
source "${VAULT_ENV_FILE:-/tmp/vault/config.env}"
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT VAULT_NAMESPACE=''
# Preserve the original device and its HMAC salt, including historical comparisons.
if ! vault audit list -format=json | jq -e 'has("lumen-stdout/")' >/dev/null; then
  vault audit enable -path=lumen-stdout file file_path=stdout log_raw=false hmac_accessor=true
fi
vault write sys/config/auditing/request-headers/traceparent hmac=false >/dev/null
AUDIT_MODE=${LUMEN_VAULT_AUDIT_MODE:-raw}
AGENT_FILTER='namespace == "verify/" and operation == "read" and (path == "database/creds/chatbot-readonly" or path == "database/creds/chatbot-readwrite" or path == "secrets/data/tavily" or path == "secrets/data/verify-admin")'
PROTECTION_FILTER='namespace == "verify/" and (path == "transit/encrypt/lumen-applications" or path == "transit/decrypt/lumen-applications" or path == "transform/encode/lumen-dni" or path == "transform/decode/lumen-dni" or path == "transform/encode/lumen-iban" or path == "transform/decode/lumen-iban")'
XAI_FILTER='namespace == "verify/" and path == "xai/creds/lumen"'
XAI_ACCESS_FILTER='namespace == "verify/" and path == "secrets/data/chatbot/xai-access"'
SPIFFE_FILTER='namespace == "verify/" and path == "spiffe/role/lumen-openai/mintjwt"'
case "$AUDIT_MODE" in
  raw)
    if ! vault audit list -format=json | jq -e 'has("lumen-spiffe-raw/")' >/dev/null; then
      vault audit enable -path=lumen-spiffe-raw \
        -description='Lumen lab: Vault-issued SPIFFE JWT-SVID for OpenAI' \
        file file_path=/proc/self/fd/2 mode=0000 log_raw=true hmac_accessor=false filter="$SPIFFE_FILTER"
    fi
    vault audit list -format=json | jq -e --arg filter "$SPIFFE_FILTER" \
      '.["lumen-spiffe-raw/"].options | .log_raw=="true" and .hmac_accessor=="false" and .filter==$filter' >/dev/null
    if ! vault audit list -format=json | jq -e 'has("lumen-agent-raw/")' >/dev/null; then
      vault audit enable -path=lumen-agent-raw \
        -description='Lumen lab: raw agent routes in verify, including denied admin probe' \
        file file_path=/dev/stdout mode=0000 log_raw=true hmac_accessor=false filter="$AGENT_FILTER"
    fi
    vault audit list -format=json | jq -e --arg filter "$AGENT_FILTER" \
      '.["lumen-agent-raw/"].options | .log_raw=="true" and .hmac_accessor=="false" and .filter==$filter' >/dev/null
    if ! vault audit list -format=json | jq -e 'has("lumen-protection-raw/")' >/dev/null; then
      vault audit enable -path=lumen-protection-raw \
        -description='Lumen lab: raw Transit and Transform requests in verify' \
        file file_path=/dev/stderr mode=0000 log_raw=true hmac_accessor=false filter="$PROTECTION_FILTER"
    fi
    vault audit list -format=json | jq -e --arg filter "$PROTECTION_FILTER" \
      '.["lumen-protection-raw/"].options | .log_raw=="true" and .hmac_accessor=="false" and .filter==$filter' >/dev/null
    if ! vault audit list -format=json | jq -e 'has("lumen-xai-raw/")' >/dev/null; then
      vault audit enable -path=lumen-xai-raw \
        -description='Lumen lab: dynamic xAI inference credentials in verify' \
        file file_path=/proc/self/fd/1 mode=0000 log_raw=true hmac_accessor=false filter="$XAI_FILTER"
    fi
    vault audit list -format=json | jq -e --arg filter "$XAI_FILTER" \
      '.["lumen-xai-raw/"].options | .log_raw=="true" and .hmac_accessor=="false" and .filter==$filter' >/dev/null
    if ! vault audit list -format=json | jq -e 'has("lumen-xai-access-raw/")' >/dev/null; then
      vault audit enable -path=lumen-xai-access-raw \
        -description='Lumen lab: RAR authorization before cached xAI use' \
        file file_path=/dev/fd/1 mode=0000 log_raw=true hmac_accessor=false filter="$XAI_ACCESS_FILTER"
    fi
    vault audit list -format=json | jq -e --arg filter "$XAI_ACCESS_FILTER" \
      '.["lumen-xai-access-raw/"].options | .log_raw=="true" and .hmac_accessor=="false" and .filter==$filter' >/dev/null
    ;;
  hmac)
    if vault audit list -format=json | jq -e 'has("lumen-spiffe-raw/")' >/dev/null; then
      vault audit disable lumen-spiffe-raw
    fi
    if vault audit list -format=json | jq -e 'has("lumen-agent-raw/")' >/dev/null; then
      vault audit disable lumen-agent-raw
    fi
    if vault audit list -format=json | jq -e 'has("lumen-protection-raw/")' >/dev/null; then
      vault audit disable lumen-protection-raw
    fi
    if vault audit list -format=json | jq -e 'has("lumen-xai-raw/")' >/dev/null; then
      vault audit disable lumen-xai-raw
    fi
    if vault audit list -format=json | jq -e 'has("lumen-xai-access-raw/")' >/dev/null; then
      vault audit disable lumen-xai-access-raw
    fi
    ;;
  *) echo 'LUMEN_VAULT_AUDIT_MODE debe ser raw o hmac' >&2; exit 2 ;;
esac
vault audit list -format=json | jq 'with_entries(.value |= {type, options})'
