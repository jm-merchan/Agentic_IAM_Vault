#!/usr/bin/env bash
# Rehearse the Markdown installation with no browser, notebooks or demo.sh start.
if [ "$(uname -s)" = Darwin ] && [ "${LUMEN_MANUAL_AWAKE:-0}" != 1 ]; then
 export LUMEN_MANUAL_AWAKE=1
 exec caffeinate -ims bash "$0" "$@"
fi
# Resume the same report directory for the separate live verification.
if [ "${1:-}" = verify ] && [ -z "${MANUAL_RUN:-}" ]; then
 pending="${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/pending-verification-run"
 if [ -s "$pending" ]; then export MANUAL_RUN=$(cat "$pending"); fi
fi
source "$(dirname "$0")/common.sh"
set -a
source "$DEMO_ENV_FILE"
set +a
pending_verification() {
 printf '%s\n' "$MANUAL_RUN" > "$MANUAL/pending-verification-run"
 printf '{"verification_pending":true,"reason":"Run live workflow verification"}\n' > "$MANUAL_RUN/verification-state.json"
 printf 'Instalación configurada. En modo console, actualiza las JWKS exportadas en Claude. Ejecuta: bash scripts/manual/rehearse.sh verify\n'
}
case ${1:-} in
 verify)
  bash scripts/manual/verify.sh
  bash scripts/manual/finalize.sh
  if [ -f "$MANUAL/pending-verification-run" ] && [ "$(cat "$MANUAL/pending-verification-run")" = "$MANUAL_RUN" ]; then
   rm "$MANUAL/pending-verification-run"
  fi
  exit 0;;
 install)
  require_model_inputs
  bash scripts/manual/install.sh
  pending_verification
  exit 0;;
 rebuild) require_model_inputs;;
 *) echo 'Uso: bash scripts/manual/rehearse.sh rebuild|install|verify'; exit 2;;
esac
printf 'Retirada completa de Lumen y reconstrucción desde las guías. Se conservan .env y prerrequisitos externos OpenAI/Verify.\n'
# Keep logs outside the directory that will be archived after removal.
mkdir -p "$LUMEN_STATE_DIR/manual-archives"
cycle=$(basename "$MANUAL_RUN")
log="$LUMEN_STATE_DIR/manual-archives/$cycle.log"
kubectl --context workshop get namespaces vault mysql lumen-observability --ignore-not-found -o json | jq '[.items[]|{name:.metadata.name,uid:.metadata.uid}]' > "$MANUAL_RUN/before.json"
bash demo.sh remove --dry-run >> "$log" 2>&1
cp "$LUMEN_STATE_DIR/remove-plan.json" "$MANUAL_RUN/remove-plan.json"
printf '→ Retirada de los recursos inventariados\n'
# Stop the public-only publisher and ngrok first; Vault is still reachable for revocation.
bash scripts/manual/stop.sh >> "$log" 2>&1
bash demo.sh remove >> "$log" 2>&1
cp "$LUMEN_STATE_DIR/last-remove.json" "$MANUAL_RUN/remove.json"
[ -z "$(kubectl --context workshop get namespaces vault mysql lumen-observability --ignore-not-found -o name)" ]
for port in 8088 8443 13306 3000 3200 4318 3100; do
 for attempt in $(seq 1 20); do
  if ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then break; fi
  sleep 1
 done
 if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then echo "Puerto $port ocupado por un proceso no retirado" >&2;exit 1;fi
done
mv "$MANUAL" "$LUMEN_STATE_DIR/manual-archives/$cycle"
mkdir -p "$MANUAL"
printf '→ Instalación desde los bloques Markdown\n'
bash scripts/manual/install.sh
pending_verification
