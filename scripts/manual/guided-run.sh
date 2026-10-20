#!/usr/bin/env bash
# Fresh environment for every selected step. Never source this in the login shell.
set +x
set -euo pipefail
source "$(dirname "$0")/../../scripts/demo/common.sh"
# Parse before sourcing: an unfinished quote must not execute half of .env.
[ -f "$DEMO_ENV_FILE" ] || fail "Falta $DEMO_ENV_FILE. Completa .env antes de ejecutar pasos."
bash -n "$DEMO_ENV_FILE" || fail 'Hay un error de sintaxis en .env; no se ha cargado ni ejecutado el paso.'
[ "${1:-}" = bash ] && [ -n "${2:-}" ] || fail 'El paso debe indicar un archivo Bash.'
bash -n "$2" || fail "El archivo $2 tiene un error de sintaxis; el paso no se ha ejecutado."
load_inputs
export LUMEN_ROOT="$DEMO_ROOT"
export MANUAL="$LUMEN_STATE_DIR/manual"
export MANUAL_RUN="$MANUAL/guided/reports"
export TENANT="$VERIFY_TENANT"
mkdir -p "$MANUAL_RUN"
chmod 700 "$MANUAL" "$MANUAL/guided" "$MANUAL_RUN"
cd "$DEMO_ROOT"
exec "$@"
