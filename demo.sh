#!/usr/bin/env bash
# Single entry point. Configuration lives in .env; generated state is local/private.
source "$(dirname "$0")/scripts/demo/common.sh"
action=${1:-start}
[ "$#" -eq 0 ] || shift
case "$action" in up) action=start;; esac
usage='Usage: ./demo.sh start|up|verify [--provider auto|xai|openai|anthropic]
       ./demo.sh prepare-openai
       ./demo.sh check|status|stop|remove [--dry-run]|blocks
       ./demo.sh block|unblock xai|database-read|database-write|decrypt'
case "$action" in
  check|status|stop) [ "$#" -eq 0 ] || fail 'Unexpected arguments'; exec bash "$DEMO_ROOT/scripts/demo/$action.sh" ;;
  start|verify|prepare-openai)
    if [ "$action" = prepare-openai ] && [ "$#" -ne 0 ]; then fail 'Usage: ./demo.sh prepare-openai (no arguments)'; fi
    if [ "$#" -ne 0 ]; then
      [ "$#" -eq 2 ] && [ "$1" = --provider ] || fail 'Usage: ./demo.sh start|verify [--provider auto|xai|openai|anthropic]'
      export LUMEN_PROVIDER_OVERRIDE=$2
      shift 2
    fi
    if [ "$action" = prepare-openai ]; then export LUMEN_PROVIDER_OVERRIDE=openai LUMEN_PREPARE_OPENAI=1; fi;;
  block|unblock) [ "$#" -eq 1 ] || fail 'Usage: ./demo.sh block|unblock xai|database-read|database-write|decrypt';
    case "$1" in xai|database-read|database-write|decrypt) ;; *) fail 'Invalid block resource';; esac ;;
  blocks) [ "$#" -eq 0 ] || fail 'Usage: ./demo.sh blocks'; exec bash "$DEMO_ROOT/scripts/demo/block.sh" blocks ;;
  remove) [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = --dry-run ]; } || fail 'Usage: ./demo.sh remove [--dry-run]';;
  -h|--help) printf '%s\nremove deletes local and Verify data and resources; start recreates them from .env.\n' "$usage"; exit 0;;
  *) printf '%s\n' "$usage"; exit 2 ;;
esac
load_inputs
case "$action" in start|verify|prepare-openai) source "$DEMO_ROOT/scripts/demo/model-provider.sh";; esac
lock="$LUMEN_STATE_DIR/deploy.lock"
if ! mkdir "$lock" 2>/dev/null; then
  owner=$(cat "$lock/pid" 2>/dev/null || true)
  if [[ "$owner" =~ ^[0-9]+$ ]] && kill -0 "$owner" 2>/dev/null; then fail 'Another demo.sh run is already in progress.'; fi
  # Without a pid the lock may belong to a run that has only just created it.
  if [ -z "$owner" ] && [ -z "$(find "$lock" -maxdepth 0 -mmin +1)" ]; then fail 'Another demo.sh run is starting.'; fi
  # The rename is atomic: of two runs reclaiming a stale lock, only one succeeds.
  mv "$lock" "$lock.stale.$$" 2>/dev/null || fail 'Another demo.sh run has taken the lock.'
  rm -rf "$lock.stale.$$"
  mkdir "$lock" 2>/dev/null || fail 'Another demo.sh run has taken the lock.'
fi
printf '%s\n' "$$" > "$lock/pid"
finish() {
  local status=$?
  if [ -n "${report:-}" ] && [ -f "$report" ]; then
    mkdir -p "$LUMEN_STATE_DIR/reports"
    cp "$report" "$LUMEN_STATE_DIR/reports/$run_id-$action.json"
  fi
  rm -f "$lock/pid"
  rmdir "$lock"
  exit "$status"
}
trap finish EXIT
run_id=$(date -u +%Y%m%dT%H%M%SZ)
run_log="$LUMEN_STATE_DIR/logs/deploy-$run_id.log"
report="$LUMEN_STATE_DIR/last-run.json"
jq -n --arg run "$run_id" --arg action "$action" --argjson dry_run "$([ "${1:-}" = --dry-run ] && echo true || echo false)" '{run:$run,action:$action,dry_run:$dry_run,completed:false,steps:[]}' > "$report"
step() {
  local name=$1; shift
  printf '→ %s\n' "$name"
  if "$@" >> "$run_log" 2>&1; then
    jq --arg name "$name" '.steps += [{name:$name,passed:true}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    printf '  OK\n'
  else
    jq --arg name "$name" '.steps += [{name:$name,passed:false}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    printf '  Failed. Private log: %s\n' "$run_log" >&2
    exit 1
  fi
}
if [ "$action" = block ] || [ "$action" = unblock ]; then
  bash "$DEMO_ROOT/scripts/demo/block.sh" "$action" "$@"
  jq '.completed=true | .steps=[{name:"Vault access control",passed:true}]' "$report" > "$report.next"
  mv "$report.next" "$report"
  exit 0
fi
if [ "$action" = remove ]; then
  if bash "$DEMO_ROOT/scripts/demo/remove.sh" "$@" 2>&1 | tee -a "$run_log"; then
    jq '.completed=true | .steps=[{name:"Demo removal (or dry run)",passed:true}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    exit 0
  else
    jq '.steps=[{name:"Demo removal",passed:false}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    printf 'Removal interrupted. Private log: %s\n' "$run_log" >&2
    exit 1
  fi
fi
if [ "$action" = prepare-openai ]; then
  step 'OpenAI prerequisites and .env' bash "$DEMO_ROOT/scripts/demo/check.sh"
  step 'Minikube and Vault' bash "$DEMO_ROOT/scripts/demo/vault.sh"
  step 'verify namespace and integration secrets' bash "$DEMO_ROOT/scripts/demo/bootstrap.sh"
  step 'Vault SPIFFE JWT-SVID' bash "$DEMO_ROOT/scripts/demo/spiffe.sh"
  step 'Public discovery and JWKS via ngrok' bash "$DEMO_ROOT/scripts/demo/ngrok.sh"
  step 'OpenAI project and service account' bash "$DEMO_ROOT/scripts/demo/openai-admin.sh"
  jq '.completed=true' "$report" > "$report.next"; mv "$report.next" "$report"
  printf '\nIssuer ready. Create the provider/mapping as described in docs/OPENAI_SPIFFE.md and save OPENAI_IDENTITY_PROVIDER_ID in .env. Then run: ./demo.sh start --provider openai\n'
  exit 0
fi
if [ "$action" = start ]; then
  select_model_provider
  step 'Prerequisites and .env' bash "$DEMO_ROOT/scripts/demo/check.sh"
  step 'Minikube, Vault, TLS, init/unseal, and plugin' bash "$DEMO_ROOT/scripts/demo/vault.sh"
  step 'MySQL Enterprise and KMIP' bash "$DEMO_ROOT/scripts/demo/mysql.sh"
  step 'verify namespace and integration secrets' bash "$DEMO_ROOT/scripts/demo/bootstrap.sh"
  step 'RAR and Vault OAuth profile' bash "$DEMO_ROOT/verify/scripts/configure-base.sh"
  step 'Python environment' bash "$DEMO_ROOT/chatbot/scripts/install.sh"
  step 'MySQL RO/RW roles and catalog' bash "$DEMO_ROOT/chatbot/scripts/01-database.sh"
  step 'OIDC, Tavily, and STS clients in Verify' bash "$DEMO_ROOT/chatbot/scripts/02-verify-apps.sh"
  step 'Three users and groups' bash "$DEMO_ROOT/chatbot/scripts/03-verify-users.sh"
  step 'Transit, tokenization, and applications' bash "$DEMO_ROOT/chatbot/scripts/06-data-protection.sh"
  step 'Policies, entities, and registered agents' bash "$DEMO_ROOT/chatbot/scripts/04-vault-agents.sh"
  step 'Optional task agents' bash "$DEMO_ROOT/chatbot/scripts/configure-task-agents.sh"
  step 'OIDC assignments and Vault groups' bash "$DEMO_ROOT/chatbot/scripts/05-sync-groups.sh"
  step 'Optional personal spaces' bash "$DEMO_ROOT/chatbot/scripts/configure-personal-spaces.sh"
  step 'Contracting with CIBA, Vault, and MySQL' bash "$DEMO_ROOT/chatbot/scripts/configure-contracts.sh"
  step 'xAI dynamic engine' bash "$DEMO_ROOT/scripts/demo/xai.sh"
  step 'xAI identity' bash "$DEMO_ROOT/chatbot/scripts/configure-xai.sh"
  step 'Vault SPIFFE JWT-SVID for OpenAI' env LUMEN_SELECTED_PROVIDER=openai bash "$DEMO_ROOT/scripts/demo/spiffe.sh"
  step 'Vault SPIFFE JWT-SVID for Claude' env LUMEN_SELECTED_PROVIDER=anthropic bash "$DEMO_ROOT/scripts/demo/spiffe.sh"
  step 'Public discovery and JWKS via ngrok' bash "$DEMO_ROOT/scripts/demo/ngrok.sh"
  step 'Claude issuer public keys (API or console)' bash "$DEMO_ROOT/scripts/demo/claude-issuer.sh"
  step 'OpenAI project and service account' bash "$DEMO_ROOT/scripts/demo/openai-admin.sh"
  load_inputs
  step 'OpenAI identity' bash "$DEMO_ROOT/chatbot/scripts/configure-openai.sh"
  step 'Claude identity' bash "$DEMO_ROOT/chatbot/scripts/configure-anthropic.sh"
  step 'Provider catalog for the selector' bash "$DEMO_ROOT/chatbot/scripts/configure-models.sh"
  step 'Correlated Vault audit' bash "$DEMO_ROOT/chatbot/scripts/enable-audit.sh"
  step 'Grafana, Loki, Tempo, and Alloy' bash "$DEMO_ROOT/chatbot/scripts/deploy-observability.sh"
  step 'Local ports and Lumen' bash "$DEMO_ROOT/scripts/demo/start.sh"
  step 'Claude: SPIFFE federation and real inference' bash "$DEMO_ROOT/chatbot/scripts/verify-anthropic.sh"
fi
step 'Runtime persistence and secret isolation' bash "$DEMO_ROOT/scripts/demo/verify-runtime.sh"
step 'Application tests' bash -c 'cd "$DEMO_ROOT/chatbot"; /tmp/vault-chatbot-venv/bin/python -m pytest -q tests'
step 'MySQL, agent permissions, and Tavily search' bash "$DEMO_ROOT/chatbot/scripts/test-infrastructure.sh"
step 'Final service status' bash "$DEMO_ROOT/scripts/demo/status.sh"
if [ "$action" = verify ]; then
  select_model_provider
  if [ "$LUMEN_SELECTED_PROVIDER" = xai ]; then
    step 'xAI: inference, denials, and real expiry' bash "$DEMO_ROOT/chatbot/scripts/verify-xai.sh"
  elif [ "$LUMEN_SELECTED_PROVIDER" = openai ]; then
    step 'OpenAI: SPIFFE JWT-SVID, token exchange, and inference' bash "$DEMO_ROOT/chatbot/scripts/verify-openai.sh"
  else
    step 'Claude: SPIFFE JWT-SVID, RFC 7523 token, and inference' bash "$DEMO_ROOT/chatbot/scripts/verify-anthropic.sh"
  fi
fi
jq '.completed=true' "$report" > "$report.next"
mv "$report.next" "$report"
printf '\nDemo ready: http://localhost:8088\nGrafana: http://localhost:3000/d/lumen-iam\nReport: %s\n' "$report"
