#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
failed=0
# Report a sealed or unreachable Vault and keep checking the rest.
if vault status -format=json 2>/dev/null | jq -e '.initialized and (.sealed|not)' >/dev/null; then
  printf 'Vault: OK\n'
else
  printf 'Vault: SEALED, UNINITIALIZED OR UNREACHABLE. ./demo.sh start unseals it and renews the port-forward.\n'; failed=1
fi
"${K[@]}" -n vault get pods -l component=server
"${K[@]}" -n mysql get pods
"${K[@]}" -n lumen-observability get deployments
for entry in 'Lumen|http://127.0.0.1:8088/health' 'Grafana|http://127.0.0.1:3000/api/health' 'Tempo|http://127.0.0.1:3200/ready' 'Loki|http://127.0.0.1:3100/ready'; do
  name=${entry%%|*}; url=${entry#*|}
  if curl -fsS --max-time 5 "$url" >/dev/null; then printf '%s: OK\n' "$name"; else printf '%s: NO DISPONIBLE\n' "$name"; failed=1; fi
done
exit "$failed"
