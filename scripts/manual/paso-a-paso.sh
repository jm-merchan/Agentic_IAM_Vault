#!/usr/bin/env bash
# Compatible with Bash 3.2; run this file, do not source it.
set +x
set -euo pipefail
command -v python3 >/dev/null || { echo 'Falta python3 en PATH.' >&2; exit 1; }
exec python3 "$(dirname "$0")/guided.py" "$@"
