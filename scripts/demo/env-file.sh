#!/usr/bin/env bash
# Sourced with the workspace root as $1. Private inputs live next to the local
# state, outside the workspace, which may be a synced folder.
LUMEN_STATE_DIR=${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}
if [ -z "${DEMO_ENV_FILE:-}" ]; then
  DEMO_ENV_FILE=$LUMEN_STATE_DIR/.env
  if [ ! -f "$DEMO_ENV_FILE" ] && [ -f "$1/.env" ]; then
    DEMO_ENV_FILE=$1/.env
    if [ -z "${LUMEN_ENV_WARNED:-}" ]; then
      printf 'WARNING: using the legacy workspace .env. Move it out of the workspace:\n  mkdir -p "%s" && mv "%s" "%s"\n' \
        "$LUMEN_STATE_DIR" "$DEMO_ENV_FILE" "$LUMEN_STATE_DIR/.env" >&2
      export LUMEN_ENV_WARNED=1
    fi
  fi
fi
export LUMEN_STATE_DIR DEMO_ENV_FILE
