#!/usr/bin/env bash
set +x
set -Eeuo pipefail
umask 077
MANUAL_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
export LUMEN_STATE_DIR=${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}
export MANUAL="$LUMEN_STATE_DIR/manual"
export MANUAL_RUN=${MANUAL_RUN:-$MANUAL_ROOT/docs/runs/$(date -u +%Y%m%dT%H%M%SZ)-manual-script}
mkdir -p "$MANUAL" "$MANUAL_RUN" "$MANUAL/blocks" "$MANUAL/logs"
export MANUAL_CODE="$MANUAL/blocks"
cd "$MANUAL_ROOT"
block() {
 local doc=$1 number=$2 target="$MANUAL_CODE/$1-$2.sh"
 awk -v wanted="$number" '/^```bash$/{n++;inside=1;next} /^```$/{inside=0} inside && n==wanted{print}' "docs/manual/$doc.md" > "$target"
 [ -s "$target" ]
 bash -n "$target"
 printf '%s\n' "$target"
}
step() {
 local manual_doc=$1 manual_number=$2 manual_source manual_log
 manual_source=$(block "$manual_doc" "$manual_number")
 manual_log="$MANUAL/logs/$manual_doc-$manual_number-${ROLE:-all}.log"
 printf '→ %s · bloque %s%s\n' "$manual_doc" "$manual_number" "${ROLE:+ ($ROLE)}"
 source "$manual_source" > "$manual_log" 2>&1
 jq -n --arg document "$manual_doc.md" --argjson block "$manual_number" --arg role "${ROLE:-}" --arg sha "$(shasum -a 256 "$manual_source" | awk '{print $1}')" '{document:$document,block:$block,role:$role,sha256:$sha,passed:true}' >> "$MANUAL/steps.jsonl"
}
background() {
 local file pid
 file=$(block "$1" "$2")
 nohup bash "$file" > "$MANUAL/logs/$3.log" 2>&1 < /dev/null &
 pid=$!
 printf '%s\t%s\t%s\n' "$3" "$pid" "$file" >> "$MANUAL/processes.tsv"
 jq -n --arg document "$1.md" --argjson block "$2" --arg service "$3" \
  --arg sha "$(shasum -a 256 "$file" | awk '{print $1}')" \
  '{document:$document,block:$block,service:$service,sha256:$sha}' >> "$MANUAL/background-blocks.jsonl"
}
wait_port() {
 local port=$1
 for retry in $(seq 1 90); do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then return 0; fi
  sleep 1
 done
 printf 'Puerto %s no disponible; revisar logs privados\n' "$port" >&2; return 1
}

# The scripted rehearsal reuses external WIF IDs; validate before any removal.
require_model_inputs() {
 local name
 for name in XAI_MANAGEMENT_API_KEY OPENAI_ADMIN_API_KEY OPENAI_PROJECT_ID OPENAI_SERVICE_ACCOUNT_ID OPENAI_IDENTITY_PROVIDER_ID NGROK_DOMAIN ANTHROPIC_FEDERATION_ISSUER_ID ANTHROPIC_FEDERATION_RULE_ID ANTHROPIC_ORGANIZATION_ID ANTHROPIC_SERVICE_ACCOUNT_ID ANTHROPIC_WORKSPACE_ID; do
  [ -n "${!name:-}" ] || { printf 'Completa %s para preparar los tres proveedores antes del ensayo.\n' "$name" >&2; return 1; }
 done
 case "${LUMEN_MODEL_PROVIDER:-auto}" in auto|openai|xai|anthropic) ;; *) echo 'Proveedor inicial no válido' >&2; return 1;; esac
}
