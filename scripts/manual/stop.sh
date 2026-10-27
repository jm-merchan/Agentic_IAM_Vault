#!/usr/bin/env bash
# Stop only processes started by this manual rehearsal, plus its older publisher/tunnel.
source "$(dirname "$0")/common.sh"
stop_tree() {
 local parent=$1 child
 while read -r child; do [ -z "$child" ] || stop_tree "$child"; done < <(pgrep -P "$parent" || true)
 kill "$parent" 2>/dev/null || true
}
if [ -f "$MANUAL/processes.tsv" ]; then
 while IFS=$'\t' read -r name pid file; do
  [[ "$pid" =~ ^[0-9]+$ ]] || exit 1
  command=$(ps -p "$pid" -o command= 2>/dev/null || true)
  case "$command" in *"$file"*) stop_tree "$pid";; '') ;; *) printf 'PID reutilizado, se conserva: %s\n' "$pid";; esac
 done < "$MANUAL/processes.tsv"
fi
# The previous interactive installation predates the process manifest.
while read -r pid command; do
 case "$command" in
  "bash $MANUAL/publish-public.sh"|"ngrok http file://$LUMEN_STATE_DIR/ngrok/public "*) stop_tree "$pid";;
  "kubectl --context workshop -n vault port-forward --address 127.0.0.1 pod/vault-0 8443:8200"|\
  "kubectl --context workshop -n mysql port-forward --address 127.0.0.1 svc/mysql-enterprise 13306:3306"|\
  "kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/grafana 3000:3000"|\
  "kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 4318:4318 3200:3200"|\
  "kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 3200:3200 4318:4318"|\
  "kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 4318:4318"|\
  "kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 3200:3200"|\
  "kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/loki 3100:3100") stop_tree "$pid";;
 esac
done < <(ps -axo pid=,command=)
