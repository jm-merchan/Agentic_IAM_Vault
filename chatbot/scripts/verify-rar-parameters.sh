#!/usr/bin/env bash
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify LUMEN_GUIDED=1 MANUAL="$LUMEN_STATE_DIR/manual"
export PYTHONPATH="$DEMO_ROOT/chatbot" LUMEN_TRACE_DIR="$LUMEN_STATE_DIR/rar-parameters/traces"
export RAR_CASES_FILE="$LUMEN_STATE_DIR/rar-parameters/cases.jsonl"
mkdir -p "$LUMEN_STATE_DIR/rar-parameters"
: > "$RAR_CASES_FILE"
for combination in writer:write supervisor:reveal supervisor:read writer:legacy; do
  role=${combination%:*}
  mode=${combination#*:}
  bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" "$role" "$mode"
  CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy \
    -ttl=5m -explicit-max-ttl=5m -display-name=lumen-rar-verification | jq -er .auth.client_token)
  export CHATBOT_BOOTSTRAP_TOKEN
  "${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$DEMO_ROOT/chatbot/scripts/verify-rar-parameters.py" "$role" "$mode"
  unset CHATBOT_BOOTSTRAP_TOKEN
done
vault status -format=json | jq '{version,initialized,sealed}' > "$LUMEN_STATE_DIR/rar-parameters/vault-version.json"
jq -s --slurpfile vault "$LUMEN_STATE_DIR/rar-parameters/vault-version.json" \
  '{vault:$vault[0],cases:.,all_passed:(length==4 and all(.[];all(.checks[];.passed))),
    scope:"Live Verify PKCE, exact OBO RAR validation, identical synthetic requests with and without parameter controls; no ACL changes, no SQL writes"}' \
  "$RAR_CASES_FILE" > "$DEMO_ROOT/chatbot/docs/rar-parameters-verification.json"
jq -e '.all_passed' "$DEMO_ROOT/chatbot/docs/rar-parameters-verification.json"
