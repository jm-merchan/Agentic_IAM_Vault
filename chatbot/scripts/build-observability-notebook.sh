#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD_DIR=$(mktemp -d /tmp/lumen-observability-notebook.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT
printf '[]' > "$BUILD_DIR/cells.json"
cell() {
  local kind=$1
  cat > "$BUILD_DIR/source"
  jq --arg kind "$kind" --rawfile source "$BUILD_DIR/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$BUILD_DIR/cells.json" > "$BUILD_DIR/next"
  mv "$BUILD_DIR/next" "$BUILD_DIR/cells.json"
}
cell markdown <<'MD'
# Lumen — permissions, Vault audit log and agent traces

Observability reference; `./demo.sh` includes these stages. **Bash** provisioning, `workshop` Kubernetes context, `lumen-observability` namespace. Grafana 13.2.4 + Loki 3.7.8 + Tempo 2.10.8 (monolithic mode) + Alloy 1.21.0-rc.0. This release candidate is pinned for the lab because it includes the fix for lost stdout/stderr lines [grafana/alloy#7080](https://github.com/grafana/alloy/pull/7080). Application instrumented with OpenTelemetry 1.45.1. ClusterIP services; browser and OTLP access through port-forwards on `127.0.0.1`. No Ingress or NodePort is published. [Current review of the interface and services](docs/runs/20261022T140230Z-workspace-review/README.md).

[Walkthrough guide with screenshots](chatbot/OBSERVABILITY.md) · [Executed verification](chatbot/docs/observability-verification.json)

Vault had no auditing enabled when this extension started. Evidence exists only from its activation onward; earlier requests are not reconstructed. The current configuration keeps `lumen-stdout/` with HMAC and adds `lumen-agent-raw/`, filtered to four read paths, and `lumen-protection-raw/`, filtered to six Transit/Transform paths in `verify`, without HMAC; `lumen-xai-raw/` covers `xai/creds/lumen`. Full JWTs, bodies and responses also appear in `vault.read` and `vault.write` (notebook 8).
MD
cell markdown <<'MD'
## 1. Enable auditing and correlation

Six root devices: the protected `lumen-stdout/` and five raw outputs (`lumen-agent-raw/`, `lumen-protection-raw/`, `lumen-xai-raw/`, `lumen-xai-access-raw/`, `lumen-spiffe-raw/`) with different filters. `traceparent` links the copies to Tempo. It does not change user or agent policies. Alloy reads the logs of the three Vault pods through the Kubernetes API, with read RBAC restricted to the `vault` namespace; it labels the copies as `audit_mode=raw` or `hmac`.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/enable-audit.sh
CODE
cell markdown <<'MD'
## 2. Deploy Grafana, Loki, Tempo and Alloy

PVCs: Loki 5 GiB, Tempo 5 GiB, Grafana 1 GiB. Log/trace retention: 7 days; local lab storage, no HA. Grafana admin: `lumen-admin`; random password stored in Vault `verify/secrets/chatbot/observability` and in the Kubernetes Secret `lumen-observability/grafana-admin`. The chatbot cannot read that secret. The script reuses the existing credential. Grafana has a 1536 MiB limit and `GOMEMLIMIT=768MiB`. When started with `demo.sh`, `launchd` restores the port-forwards if their connection drops.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/deploy-observability.sh
for deployment in grafana loki tempo alloy; do
  kubectl --context workshop -n lumen-observability rollout status deployment/$deployment --timeout=180s
done
CODE
cell markdown <<'MD'
## 3. Open local ports and start the instrumented application

For the complete deployment from the root:

```bash
./demo.sh
```

The launcher keeps the port-forwards and the application running as user services. The individual scripts are for maintenance; no extra terminals are needed. Configuration is read from `.env`.

`run.sh` uses `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces`. Bootstrap tokens remain temporary and limited. The provider is chosen in the banner among the loaded OpenAI/xAI/Claude profiles; each one uses its own Vault identity.

LLM capture is enabled by default with `LUMEN_TRACE_CONTENT=1`: messages, responses, tools, arguments and results, with credentials redacted. Independently, `LUMEN_TRACE_VAULT_RAW=1` stores the Vault exchange, JWTs and credentials in clear text. Per-field limit: 65,536 bytes, with truncation flagged; Tempo uses `distributor.max_attribute_bytes=131072`. To go back to metadata only for new traces: `LUMEN_TRACE_CONTENT=0 LUMEN_TRACE_VAULT_RAW=0 bash chatbot/scripts/run.sh`. The audit log has its own switch (section 8).

In Grafana, open an `xai.chat`, `openai.chat` or `anthropic.chat` span and review `lumen.user.message`, `gen_ai.input.messages`, `gen_ai.output.messages` and `gen_ai.tool.definitions`. In `tool.*`, review `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result`. The chat's **View latest trace** link offers readable panels per call. Earlier traces contain no messages. The LangChain callback content is captured, not the exact HTTP body or the model's internal reasoning.

The local viewer offers an interactive diagram with per-service icons, destination filters, request/return arrows and details for each call. In the lab, **Ver valores sensibles / View sensitive values** opens the OAuth and HTTP Basic values (including `client_secret`), JWT-SVID, MySQL credentials and encryption/decryption bodies. New captures stay in memory for ten minutes; raw Vault/SPIFFE captures follow the trace retention. [Full scope](chatbot/OBSERVABILITY.md#valores-de-cada-llamada).

Each Vault step includes **Cómo decide Vault / How Vault decides**, a drop-down independent of the sensitive values. It queries the correlated audit log to show the identity, the OBO actor, the policies that granted access and the recorded RAR. It distinguishes OAuth, OBO, native token, login and public keys; if events are missing or do not identify the cause of a denial, it says so instead of reconstructing historical policies from the current configuration. [Available data and limits](chatbot/OBSERVABILITY.md#cómo-decide-vault).

![Logic and evidence of a Vault decision](docs/screenshots/current/vault-decision.jpg)

**EN / ES** switches titles, explanations, formats and pagination according to the Lumen preference; original values are never translated. The initial language comes from the browser unless a manual choice has been saved. Grafana keeps its own language. [Bilingual check](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües) · [Evidence from October 20](chatbot/docs/language-verification.json).

- Chat: <http://localhost:8088>
- Dashboard: <http://localhost:3000/d/lumen-iam>
- Look up the Grafana password in the Vault UI: namespace `verify` → `secrets` → `chatbot/observability`. Do not paste it into a notebook cell.

`./demo.sh start` keeps the Grafana, Loki and Tempo port-forwards running with `launchd`. If you run this notebook without the launcher and the next check cannot connect to port 3000, open them in another terminal with `bash chatbot/scripts/observability-forward.sh`.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:3000/api/health
curl -fsS http://127.0.0.1:3100/ready
curl -fsS http://127.0.0.1:3200/ready
CODE
cell markdown <<'MD'
## 4. Visual walkthrough per user

In IBM Verify select **Cloud Directory**. Passwords are in `verify/secrets/chatbot/users/{reader,writer,supervisor}`.

| Action | Reader | Writer | Supervisor |
|---|---|---|---|
| Catalog/inventory/masked inbox | Yes | Yes | Yes |
| Save five-step application | No | Yes, with review and confirmation | No |
| Reveal profile, DNI and IBAN | No, 403 | No, 403 | Yes, Transit/Transform |
| Obtain Vault RW role | 403 | 200 | 403 |
| Administrative secret | 403 | 403 | 403 |
| Public search | Autonomous Tavily agent | Autonomous Tavily agent | Autonomous Tavily agent |

1. Reader: browse the catalog and inventory; «Take the next step» blocks locally without calling Vault.
2. «Check limits in Vault» shows nine real OBO requests: RO/RW/admin, Transit encrypt/decrypt and Transform encode/decode of DNI and IBAN. [Updated matrix and screenshots](docs/PERMISSION_PROBES.md).
3. Writer: ask the agent to prepare Luz Noche, continue to the form, accept fictitious suggestions with Tab, review and save. «Applications» shows the shared masked inbox.
4. Reader and writer cannot reveal. Supervisor retrieves the same record but does not obtain SQL RW.
5. «A wider perspective» uses Client Credentials → Agent Registry → Vault/Tavily.

[Results and screenshots from the real rebuild](docs/E2E_OPENAI_VERIFICATION.md).

![Reader: local block](docs/screenshots/current/reader-write-denied.jpg)
![Writer: application saved](docs/screenshots/current/writer-save-success.jpg)

MD
cell markdown <<'MD'
## 5. From the chat to the audit log and the trace

Copy the **Trace ID** from the Activity panel and paste it into the dashboard. Each Vault request produces a `request` and a `response` with the same `request.id`. The `traceparent` header contains the `trace_id` and `span_id` of `vault.read`, also for 403 responses.

In a log: menu → **Show log details** → **TraceID** field → **Abrir traza**. In Tempo: open the `vault.read` span → **Related logs**. The tree shows `deepagents.run`, `xai.chat`, `openai.chat` or `anthropic.chat` calls, tools, STS, Vault and SQL or Tavily queries. OpenAI and Claude add `spiffe.mint_jwt_svid` and their `openai.token_exchange` or `anthropic.token_exchange` exchange. The OIDC login generates a separate trace, with user and role, once its signature has been validated.

![Current Supervisor audit](docs/screenshots/current/grafana-audit.jpg)
![OpenAI, SPIFFE and OBO catalog in Tempo](docs/screenshots/current/grafana-openai-trace.jpg)

This measures calls made from the chatbot: it does not instrument the internal servers of xAI/OpenAI, Verify, Vault or Tavily, nor does it record the model's private reasoning. The Vault audit log attests to credential issuance/denial; SQL statements are observed through client spans. Independent SQL auditing requires MySQL's own audit facility.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
# Paste a recent Trace ID from the interface.
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Paste a recent Trace ID and rerun the cell.'; exit 0; }
curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode "query={service=\"vault-audit\"} |= \"$TRACE_ID\"" \
  --data-urlencode since=24h --data-urlencode limit=100 \
  | jq '[.data.result[].values[][1]|fromjson|{time,type,request_id:.request.id,path:.request.path,allowed:.auth.policy_results.allowed,policies:.auth.policies,actor:.auth.metadata.actor_entity_name}]|sort_by(.time)'
CODE
cell markdown <<'MD'
## 6. Verify correlation and capture mode

The script queries Tempo and Loki and checks the pairs with the same `request.id` and `traceparent`. It prefers the raw copy when available and verifies that the JWTs and responses match the span; for protected records it checks the HMAC. It exports only metadata, booleans and sizes, never credentials.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Paste a recent Trace ID and rerun the cell.'; exit 0; }
bash chatbot/scripts/verify-observability.sh "$TRACE_ID"
cd chatbot
/tmp/vault-chatbot-venv/bin/python -m pytest -q tests
CODE
cell markdown <<'MD'
## 7. Query the LLM messages and tools

Use the ID of a new query. The end-to-end report compares the captured fields with Tempo and checks that the full form data is not sent to the model. The notebook is distributed without outputs; the next cell shows the content when it runs.

[Historical screenshot: Input text in the Lumen viewer](docs/runs/20261014T162141Z/screenshots/25-model-input.jpg)
MD
cell code <<'CODE'
%%bash
set -euo pipefail
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Paste a recent Trace ID and rerun the cell.'; exit 0; }
curl -fsS "http://127.0.0.1:3200/api/traces/$TRACE_ID" | jq '
  [.batches[]?.scopeSpans[]?.spans[]?
   | select(.name == "xai.chat" or .name == "openai.chat" or .name == "anthropic.chat" or (.name | startswith("tool.")))
   | {name,attributes:[.attributes[]?
       | select(.key | test("^(gen_ai\\.(input.messages|output.messages|tool.definitions|tool.call.arguments|tool.call.result)|lumen\\.(user.message|model.parameters))$"))
       | {field:.key,content:(.value.stringValue|fromjson)}]}]'
CODE
awk '/^## 8\. /{copy=1} copy' chatbot/OBSERVABILITY.md \
  | sed 's|](docs/|](chatbot/docs/|g; s|](scripts/|](chatbot/scripts/|g; s|](tests/|](chatbot/tests/|g; s|](../8_Lumen_|](8_Lumen_|g; s|](../docs/|](docs/|g' | cell markdown
cell code <<'CODE'
%%bash
set -euo pipefail
# Deliberately shows JWTs and responses in clear text. Do not save these outputs to the repository.
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Paste a recent Trace ID and rerun the cell.'; exit 0; }
curl -fsS "http://127.0.0.1:3200/api/traces/$TRACE_ID" | jq '
  [.batches[]?.scopeSpans[]?.spans[]? | select(.name=="vault.read" or .name=="vault.write") |
   {name,attributes:[.attributes[]? | select(.key | test("^vault\\.(http\\.(request|response)|auth\\.jwt(\\.decoded)?)$")) |
      {field:.key,content:(.value.stringValue|fromjson)}]}]'
CODE
cell markdown <<'MD'
## Scope and operation

- All auditable requests after the device is enabled are captured, including administrative ones. Some status/health paths do not generate audit entries by design. Blocked local actions and traffic to other services are not Vault requests.
- Grafana is an operator console; its credentials are not given to chatbot users. Loki/Tempo are ClusterIP services without their own authentication, reached through localhost port-forwards. The model/tool fields redact credentials; `LUMEN_TRACE_VAULT_RAW=1` mode deliberately keeps Vault JWTs and responses in clear text.
- Each chat action has its own trace. External searches use predefined public topics. No private MySQL data is sent to Tavily.
- Local `spans.jsonl` in `/tmp/lumen-telemetry`, directory 700/file 600; Tempo keeps traces for 7 days. This auxiliary file is not rotated and should be deleted at the end of the lab.
- Alloy collects stdout; a prolonged outage or container log rotation can lose pending events. This configuration is not immutable production audit storage. For that goal: a redundant durable sink, retention/rotation and external storage.
- If you change the Loki/Tempo/Alloy/datasource ConfigMaps, restart only the affected deployment. Grafana dashboards reload automatically. Repeating the deployment does not restart services.

Sources: [Vault auditing](https://developer.hashicorp.com/vault/docs/audit), [Audit headers](https://developer.hashicorp.com/vault/api-docs/system/config-auditing), [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/), [Tempo/Loki correlation](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/configure-trace-to-logs/), [Alloy Kubernetes](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/).
MD
jq -n --slurpfile cells "$BUILD_DIR/cells.json" '{cells:$cells[0],metadata:{kernelspec:{display_name:"Python 3 (Bash cells)",language:"python",name:"python3"},language_info:{name:"python",version:"3.12"}},nbformat:4,nbformat_minor:4}' > 7_Lumen_Observability.ipynb
printf 'Created 7_Lumen_Observability.ipynb\n'
