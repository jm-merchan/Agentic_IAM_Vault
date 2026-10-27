#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
HERE=$(cd "$(dirname "$0")/.." && pwd)
source "$HERE/../verify/scripts/common.sh"
K=(kubectl --context workshop)
NS=lumen-observability
"${K[@]}" create namespace "$NS" --dry-run=client -o yaml | "${K[@]}" apply -f -
for item in 'loki-config:loki.yaml' 'tempo-config:tempo.yaml' 'alloy-config:config.alloy' 'grafana-datasources:datasources.yaml' 'grafana-providers:dashboards.yaml' 'grafana-dashboards:dashboard.json'; do
  name=${item%%:*}; file=${item#*:}
  "${K[@]}" -n "$NS" create configmap "$name" --from-file="$file=$HERE/observability/$file" --dry-run=client -o yaml | "${K[@]}" apply -f -
done
# Persistent operator credential stays in Vault, outside the chatbot bootstrap policy.
if ! vault kv metadata get -mount=secrets chatbot/observability >/dev/null 2>&1; then
  openssl rand -hex 24 | tr -d '\n' > "$TMP_WORK/password"
  jq -n --rawfile password "$TMP_WORK/password" '{username:"lumen-admin",password:$password,url:"http://localhost:3000"}' | kv_write chatbot/observability
fi
kv_read chatbot/observability | jq -jr .password > "$TMP_WORK/password"
"${K[@]}" -n "$NS" create secret generic grafana-admin --from-file=password="$TMP_WORK/password" --dry-run=client -o json | "${K[@]}" apply -f -
"${K[@]}" apply -f "$HERE/observability/stack.yaml"
printf 'Deployment applied. Check with: kubectl --context workshop -n %s get pods\n' "$NS"
