#!/usr/bin/env bash
# Verify stored Tempo spans against real Vault audit events in Loki; no secret output.
set -euo pipefail
umask 077
HERE=$(cd "$(dirname "$0")/.." && pwd)
OBS_TMP=$(mktemp -d /tmp/lumen-observability-check.XXXXXX)
trap 'rm -rf "$OBS_TMP"' EXIT
printf '[]' > "$OBS_TMP/reports"
if [ "$#" -eq 0 ]; then
  echo 'Uso: bash chatbot/scripts/verify-observability.sh TRACE_ID [TRACE_ID ...]' >&2
  exit 2
fi
for tid in "$@"; do
  [[ "$tid" =~ ^[0-9a-f]{32}$ ]] || { echo 'Trace ID inválido' >&2; exit 2; }
  curl -fsS --max-time 15 -H 'Accept: application/json' "http://127.0.0.1:3200/api/traces/$tid" > "$OBS_TMP/tempo"
  curl -fsS --max-time 15 -G http://127.0.0.1:3100/loki/api/v1/query_range \
    --data-urlencode "query={service=\"vault-audit\"} |= \"$tid\"" \
    --data-urlencode since=24h --data-urlencode limit=1000 > "$OBS_TMP/loki"
  jq '[.batches[].scopeSpans[].spans[]]' "$OBS_TMP/tempo" > "$OBS_TMP/spans"
  jq -f "$HERE/scripts/normalize-vault-audit.jq" "$OBS_TMP/loki" > "$OBS_TMP/audit"
  # A standby can audit its forwarding attempt with a second request ID. The
  # active node pair is the operation that returns credentials to the client.
  jq -e 'length>0' "$OBS_TMP/spans" >/dev/null
  # Prefer the raw copy. Exact value comparisons require that Vault route to
  # be included in enable-audit.sh's raw filters; HMAC alone cannot prove equality.
  jq -e 'all(.[]; ._lumen_audit_mode as $mode | all((.response.data.password?, .response.data.username?, .response.data.data.TAVILY_API_KEY?)|select(.!=null); startswith("hmac-sha256:") == ($mode != "raw")))' "$OBS_TMP/audit" >/dev/null
  jq -n --slurpfile spans "$OBS_TMP/spans" --slurpfile audit "$OBS_TMP/audit" \
    -f "$HERE/scripts/verify-vault-raw.jq" > "$OBS_TMP/raw_checks"
  if ! jq -e 'all(.[]; .passed)' "$OBS_TMP/raw_checks" >/dev/null; then
    printf '%s: no se pudo acreditar la comparación completa de valores raw.\n' "$tid" >&2
    printf 'Comprueba los filtros de enable-audit.sh; KV personal y contratos tienen auditoría HMAC.\n' >&2
    jq '[.[] | select(.passed|not)]' "$OBS_TMP/raw_checks" >&2
    exit 1
  fi
  # Each client span has its matching request + response, including HTTP 403.
  jq -r '.[]|select(.name=="vault.read" or .name=="vault.write")|.spanId' "$OBS_TMP/spans" | while IFS= read -r encoded; do
    sid=$(printf '%s' "$encoded" | openssl base64 -d -A | od -An -tx1 | tr -d ' \n')
    jq -e --arg parent "00-$tid-$sid-01" \
      '[.[]|select(.request.headers.traceparent[0]==$parent)] | length==2 and (map(.type)|sort)==["request","response"] and (map(.request.id)|unique|length)==1' "$OBS_TMP/audit" >/dev/null
  done
  # The intentionally local app denial has no Vault audit event.
  jq -n --arg tid "$tid" --slurpfile spans "$OBS_TMP/spans" --slurpfile audit "$OBS_TMP/audit" --slurpfile checks "$OBS_TMP/raw_checks" '{
    trace_id:$tid, passed:true, span_count:($spans[0]|length),
    operations:[$spans[0][]|.name],raw_capture_checks:$checks[0],
    vault_requests:[$audit[0][]|select(.type=="response")|{
      request_id:.request.id,path:.request.path,namespace:.request.namespace.path,
      allowed:.auth.policy_results.allowed,policies:.auth.policies,
      human_or_agent_entity:.auth.entity_id,actor:.auth.metadata.actor_entity_name,
      traceparent:.request.headers.traceparent[0],audit_mode:._lumen_audit_mode
    }]
  }' > "$OBS_TMP/report"
  jq --slurpfile item "$OBS_TMP/report" '.+$item' "$OBS_TMP/reports" > "$OBS_TMP/next"
  mv "$OBS_TMP/next" "$OBS_TMP/reports"
  printf '%s · spans y pares de auditoría correlacionados\n' "$tid"
done
REPORT_FILE=${LUMEN_OBSERVABILITY_REPORT:-$HERE/docs/observability-verification.json}
jq -n --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --slurpfile reports "$OBS_TMP/reports" \
  '{checked_at:$date,all_passed:true,traces:$reports[0]}' > "$REPORT_FILE"
printf 'Informe sin credenciales: %s\n' "$REPORT_FILE"
