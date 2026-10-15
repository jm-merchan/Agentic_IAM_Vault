#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
for deployment in grafana tempo loki alloy; do
  "${K[@]}" -n lumen-observability rollout status "deployment/$deployment" --timeout=240s
done
start_forward grafana lumen-observability svc/grafana 3000 3000
start_forward tempo-otlp lumen-observability svc/tempo 4318 4318
start_forward tempo lumen-observability svc/tempo 3200 3200
start_forward loki lumen-observability svc/loki 3100 3100
wait_http http://127.0.0.1:3000/api/health
wait_http http://127.0.0.1:3200/ready
wait_http http://127.0.0.1:3100/ready
pid=$(port_pid 8088 || true)
if [ -n "$pid" ]; then
  command=$(ps -p "$pid" -o command=)
  cwd=$(lsof -a -p "$pid" -d cwd -Fn | sed -n 's/^n//p')
  [[ "$command" == *python*"-m app.main"* && ( "$cwd" = "$DEMO_ROOT/chatbot" || "$cwd" = "$LUMEN_STATE_DIR/runtime/chatbot" ) ]] || fail 'Puerto 8088 ocupado por una aplicación distinta; no se detiene.'
  kill "$pid"
  for attempt in $(seq 1 30); do
    [ -n "$(port_pid 8088 || true)" ] || break
    sleep 1
  done
  [ -z "$(port_pid 8088 || true)" ] || fail 'La instancia anterior de Lumen no se ha detenido.'
fi
# launchd cannot access Google Drive under macOS privacy controls. Deploy an
# isolated runtime outside CloudStorage; no static integration secrets copied.
runtime="$LUMEN_STATE_DIR/runtime/chatbot"
mkdir -p "$runtime/app" "$runtime/static" "$runtime/scripts" "$runtime/docs"
rsync -a --delete --exclude __pycache__ "$DEMO_ROOT/chatbot/app/" "$runtime/app/"
rsync -a --delete "$DEMO_ROOT/chatbot/static/" "$runtime/static/"
cp "$DEMO_ROOT/chatbot/scripts/run.sh" "$runtime/scripts/run.sh"
start_managed lumen /bin/bash "$runtime/scripts/run.sh"
wait_http http://127.0.0.1:8088/health
port_pid 8088 > "$LUMEN_STATE_DIR/pids/lumen.pid"
echo 'Lumen: http://localhost:8088 | Grafana: http://localhost:3000/d/lumen-iam'
