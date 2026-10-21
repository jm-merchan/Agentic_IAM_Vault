#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
bash "$root/verify/scripts/configure-rar.sh"
bash "$root/chatbot/scripts/configure-rar-fixtures.sh"
