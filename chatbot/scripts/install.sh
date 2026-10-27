#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=/tmp/vault-chatbot-venv
command -v uv >/dev/null || { echo 'Install uv from https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
# /tmp is shared: this interpreter later runs with Vault administrative credentials.
if [ -L "$VENV" ] || { [ -e "$VENV" ] && [ "$(stat -f %u "$VENV")" != "$(id -u)" ]; }; then
  echo "$VENV is a link or belongs to another user; remove it before installing." >&2; exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  uv venv --python 3.12 "$VENV"
fi
chmod go-w "$VENV"
uv pip install --python "$VENV/bin/python" -r requirements.lock.txt
