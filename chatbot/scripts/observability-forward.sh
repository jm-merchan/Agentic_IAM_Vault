#!/usr/bin/env bash
set -euo pipefail
umask 077
PIDS=()
trap 'for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill "$pid" 2>/dev/null || true; done' EXIT INT TERM
for deployment in grafana tempo loki alloy; do
  kubectl --context workshop -n lumen-observability rollout status "deployment/$deployment" --timeout=180s
done
for spec in grafana:3000:3000 tempo:4318:4318 tempo:3200:3200 loki:3100:3100; do
  svc=${spec%%:*}; ports=${spec#*:}; local_port=${ports%%:*}
  if ! lsof -nP -iTCP:"$local_port" -sTCP:LISTEN >/dev/null 2>&1; then
    kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 "svc/$svc" "$ports" >"/tmp/lumen-forward-$local_port.log" 2>&1 &
    PIDS+=("$!")
  fi
done
printf 'Grafana: http://localhost:3000/d/lumen-iam | OTLP: http://127.0.0.1:4318/v1/traces\n'
wait
