#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
vault status -format=json | jq -e '.initialized and (.sealed|not)' >/dev/null
"${K[@]}" -n vault get pods -l component=server
"${K[@]}" -n mysql get pods
"${K[@]}" -n lumen-observability get deployments
failed=0
for entry in 'Lumen|http://127.0.0.1:8088/health' 'Grafana|http://127.0.0.1:3000/api/health' 'Tempo|http://127.0.0.1:3200/ready' 'Loki|http://127.0.0.1:3100/ready'; do
  name=${entry%%|*}; url=${entry#*|}
  if curl -fsS --max-time 5 "$url" >/dev/null; then printf '%s: OK\n' "$name"; else printf '%s: NO DISPONIBLE\n' "$name"; failed=1; fi
done
exit "$failed"
