#!/usr/bin/env bash
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify LUMEN_GUIDED=1
export MANUAL="$LUMEN_STATE_DIR/manual"
export PYTHONPATH="$DEMO_ROOT/chatbot"
export LUMEN_TRACE_DIR="$LUMEN_STATE_DIR/task-agents/traces"
export TASK_AGENT_CASES="$LUMEN_STATE_DIR/task-agents/cases.jsonl"
mkdir -p "$LUMEN_STATE_DIR/task-agents" "$MANUAL"
: > "$TASK_AGENT_CASES"
for mode in legacy read write reveal; do
  for role in reader writer supervisor; do
    bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" "$role" "$mode"
    CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy \
      -ttl=5m -explicit-max-ttl=5m -display-name=lumen-task-agent-verification | jq -er .auth.client_token)
    export CHATBOT_BOOTSTRAP_TOKEN
    "${CHATBOT_PYTHON:-/tmp/vault-chatbot-venv/bin/python}" "$DEMO_ROOT/chatbot/scripts/verify-task-agents.py" "$role" "$mode"
    unset CHATBOT_BOOTSTRAP_TOKEN
  done
done
jq -s '{cases:.,all_passed:(length==12 and all(.[];all(.checks[];.passed))),
  scope:"Live Verify Authorization Code + PKCE, OBO, Vault ceilings, SQL catalogue; synthetic protection payloads; test DB leases revoked"}' \
  "$TASK_AGENT_CASES" > "$DEMO_ROOT/chatbot/docs/task-agents-verification.json"
jq -e .all_passed "$DEMO_ROOT/chatbot/docs/task-agents-verification.json"
