#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Instala uv desde https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
if [ ! -x /tmp/vault-chatbot-venv/bin/python ]; then
  uv venv --python 3.12 /tmp/vault-chatbot-venv
fi
uv pip install --python /tmp/vault-chatbot-venv/bin/python -r requirements.lock.txt
