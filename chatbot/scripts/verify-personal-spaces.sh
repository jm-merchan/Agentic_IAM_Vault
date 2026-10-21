#!/usr/bin/env bash
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify LUMEN_GUIDED=1 MANUAL="$LUMEN_STATE_DIR/manual"
export PYTHONPATH="$DEMO_ROOT/chatbot" LUMEN_TRACE_DIR="$LUMEN_STATE_DIR/personal-spaces/traces"
export PERSONAL_CASES_FILE="$LUMEN_STATE_DIR/personal-spaces/cases.jsonl"
mkdir -p "$LUMEN_STATE_DIR/personal-spaces"
: > "$PERSONAL_CASES_FILE"
for combination in ${PERSONAL_COMBINATIONS:-reader:legacy writer:legacy supervisor:legacy reader:read writer:read supervisor:read reader:write writer:write supervisor:write reader:reveal writer:reveal supervisor:reveal}; do
  role=${combination%:*}; mode=${combination#*:}
  bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" "$role" "$mode"
  CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m -display-name=lumen-personal-verification | jq -er .auth.client_token)
  export CHATBOT_BOOTSTRAP_TOKEN
  "${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$DEMO_ROOT/chatbot/scripts/verify-personal-spaces.py" "$role" "$mode"
  unset CHATBOT_BOOTSTRAP_TOKEN
done
vault status -format=json | jq '{version,initialized,sealed}' > "$LUMEN_STATE_DIR/personal-spaces/vault-version.json"
jq -s --slurpfile vault "$LUMEN_STATE_DIR/personal-spaces/vault-version.json" '{vault:$vault[0],cases:.,all_passed:(length>0 and all(.[];all(.checks[];.passed))),scope:"Real Verify PKCE/OBO, per-human KV template, cross-owner read/list/write denials, task ceilings and CAS; synthetic personal values only"}' "$PERSONAL_CASES_FILE" > "$DEMO_ROOT/chatbot/docs/personal-spaces-verification.json"
jq -e '.all_passed' "$DEMO_ROOT/chatbot/docs/personal-spaces-verification.json"
