# 09 · Vault audit log and Grafana traces

[Index](README.md) · Requires [01](01-vault.md) · Continue with [Startup](10-aplicacion.md)

## 1. Enable auditing in the root namespace

This can be done right after initializing Vault, before configuring anything else, if you also want to audit provisioning. It does not retroactively capture earlier calls.


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
export VAULT_NAMESPACE=''
vault audit list -format=json
vault audit enable -path=lumen-stdout file file_path=stdout log_raw=false hmac_accessor=true
vault write sys/config/auditing/request-headers/traceparent hmac=false
```

On a freshly initialized Vault, `vault audit list` in table format returns exit code 2 when there are no devices, which would stop a session running with `set -e`. The JSON variant returns `{}` and lets you continue.

If `lumen-stdout/` already exists, keep it and its HMAC salt; do not disable it to recreate it. The general device protects values. The additional devices below store raw data exclusively for the demo paths, reproducing the requested lab mode.

## 2. Add filtered raw devices

These logs include JWTs, issued credentials and data-protection responses in plaintext; they are stored in the local lab next to the traces. This is a deliberate observability configuration, not a required property of Agentic IAM.

```bash
AGENT_FILTER='namespace == "verify/" and operation == "read" and (path == "database/creds/chatbot-readonly" or path == "database/creds/chatbot-readwrite" or path == "secrets/data/tavily" or path == "secrets/data/verify-admin")'
PROTECTION_FILTER='namespace == "verify/" and (path == "transit/encrypt/lumen-applications" or path == "transit/decrypt/lumen-applications" or path == "transform/encode/lumen-dni" or path == "transform/decode/lumen-dni" or path == "transform/encode/lumen-iban" or path == "transform/decode/lumen-iban")'
XAI_FILTER='namespace == "verify/" and path == "xai/creds/lumen"'
XAI_ACCESS_FILTER='namespace == "verify/" and path == "secrets/data/chatbot/xai-access"'
SPIFFE_FILTER='namespace == "verify/" and (path == "spiffe/role/lumen-openai/mintjwt" or path == "spiffe/role/lumen-anthropic/mintjwt")'
```

```bash
vault audit enable -path=lumen-agent-raw file \
  file_path=/dev/stdout mode=0000 log_raw=true hmac_accessor=false filter="$AGENT_FILTER"
vault audit enable -path=lumen-protection-raw file \
  file_path=/dev/stderr mode=0000 log_raw=true hmac_accessor=false filter="$PROTECTION_FILTER"
vault audit enable -path=lumen-xai-raw file \
  file_path=/proc/self/fd/1 mode=0000 log_raw=true hmac_accessor=false filter="$XAI_FILTER"
vault audit enable -path=lumen-xai-access-raw file \
  file_path=/dev/fd/1 mode=0000 log_raw=true hmac_accessor=false filter="$XAI_ACCESS_FILTER"
vault audit enable -path=lumen-spiffe-raw file \
  file_path=/proc/self/fd/2 mode=0000 log_raw=true hmac_accessor=false filter="$SPIFFE_FILTER"
vault audit list -format=json | jq 'with_entries(.value |= {type,options})'
```

Skip the `enable` commands for devices that already exist and compare their options. The different stdout/stderr paths make it possible to tell the devices apart. The same request can appear in both the HMAC and the raw logs: count unique request IDs, not lines.

## 3. Prepare the ConfigMaps and the Grafana password

[stack.yaml](../../chatbot/observability/stack.yaml) deploys Grafana, Tempo, Loki and Alloy, with persistent volumes and internal services. Alloy has a Role/RoleBinding in `vault` to read pods and logs; its ServiceAccount lives in `lumen-observability`.

```bash
export VAULT_NAMESPACE=verify
"${K[@]}" create namespace lumen-observability --dry-run=client -o yaml | "${K[@]}" apply -f -
for item in 'loki-config:loki.yaml' 'tempo-config:tempo.yaml' 'alloy-config:config.alloy' \
  'grafana-datasources:datasources.yaml' 'grafana-providers:dashboards.yaml' 'grafana-dashboards:dashboard.json'; do
  name=${item%%:*}; file=${item#*:}
  "${K[@]}" -n lumen-observability create configmap "$name" \
    --from-file="$file=chatbot/observability/$file" --dry-run=client -o yaml | "${K[@]}" apply -f -
done
```

Only if `secrets/chatbot/observability` does not exist yet, generate the credential:

```bash
openssl rand -hex 24 | tr -d '\n' > "$MANUAL/grafana-password"
jq -n --rawfile password "$MANUAL/grafana-password" \
  '{username:"lumen-admin",password:$password,url:"http://localhost:3000"}' | \
  vault kv put -mount=secrets chatbot/observability -
```

Read it from Vault and use it as a Kubernetes Secret. On a Grafana instance that is already initialized, changing the Secret does not automatically rotate its persisted password; keep the existing credential.

```bash
vault kv get -format=json -mount=secrets chatbot/observability | \
  jq -jr .data.data.password > "$MANUAL/grafana-password"
"${K[@]}" -n lumen-observability create secret generic grafana-admin \
  --from-file="password=$MANUAL/grafana-password" --dry-run=client -o json | "${K[@]}" apply -f -
rm -- "$MANUAL/grafana-password"
"${K[@]}" apply -f chatbot/observability/stack.yaml
for name in grafana tempo loki alloy; do
  "${K[@]}" -n lumen-observability rollout status "deployment/$name" --timeout=240s
done
```

Versions pinned in the manifest: Grafana 13.2.4, Loki 3.7.8, Tempo 2.10.8 and Alloy **v1.21.0-rc.0**. Alloy is a release candidate, chosen for its fix for lost events when timestamps are interleaved; it is not presented as a stable release. [Issue and validation for this demo](../E2E_OPENAI_VERIFICATION.md).

## 4. Open the local ports

Each command needs its own terminal; keep them open. Do not duplicate an existing forward:

```bash
kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/grafana 3000:3000
```

```bash
kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 4318:4318 3200:3200
```

```bash
kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/loki 3100:3100
```

Check health from the main terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:3000/api/health
curl --fail --silent --show-error http://127.0.0.1:3200/ready
curl --fail --silent --show-error http://127.0.0.1:3100/ready
```

## 5. Access and correlate requests

Grafana: [Lumen dashboard](http://localhost:3000/d/lumen-iam), user `lumen-admin`. On macOS, copy its password without printing it:

```bash
vault kv get -format=json -mount=secrets chatbot/observability | jq -jr .data.data.password | pbcopy
```

The app exports OTLP to `http://127.0.0.1:4318/v1/traces`; Alloy collects the Vault audit logs and sends them to Loki. The W3C `traceparent` header links the two. The `vault.request_id` detail identifies the request/response pair; calls made with the Vault CLI produce audit logs but **do not create Lumen spans automatically**.

After a UI action, open **Ver última traza → Ver en Grafana** (**View latest trace → View in Grafana** in English). The Lumen viewer first shows the call diagram, with service icons, a destination filter and details when you select an arrow. **EN / ES** switches titles, explanations and pagination; technical names and captured values are kept as they are. In the lab, **Ver valores sensibles / View sensitive values** opens the OAuth/HTTP Basic credentials, SVID, dynamic credentials and bodies of the corresponding operation. [Viewer scope and retention](../../chatbot/OBSERVABILITY.md#valores-de-cada-llamada) · [Check languages](10-aplicacion.md#idioma-y-comprobaciones-bilingües).

You can also query using the real Trace ID of that action:

```bash
read -r -p 'Trace ID (32 hex characters): ' TRACE_ID
[[ "$TRACE_ID" =~ ^[0-9a-f]{32}$ ]]
curl --fail --silent --show-error "http://127.0.0.1:3200/api/traces/$TRACE_ID" \
  > "$MANUAL/trace.json"
LOKI_QUERY="{service=\"vault-audit\"} |= \"$TRACE_ID\""
curl --fail --silent --show-error --get http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode "query=$LOKI_QUERY" --data-urlencode 'since=1h' --data-urlencode 'limit=500' \
  > "$MANUAL/audit-trace.json"
jq '[.data.result[].values[]]|length' "$MANUAL/audit-trace.json"
```

In Loki Explore, use `{service="vault-audit",audit_mode="raw"}` and filter by Trace ID or `request.id`. Tempo shows the model, prompts/responses, tools, OBO and Vault calls. The complete JSON files may contain lab secrets: keep them in `$MANUAL`.

Explicit SVID fields in raw mode: `spiffe.jwt_svid`, `spiffe.jwt_svid.decoded`, `openai.exchange.subject_token`. The Vault access JWTs appear in `vault.auth.jwt`; the complete request and response, in `vault.http.request` / `vault.http.response`. The viewer also shows `guardrail.energy_scope`. [Tracing content and scope](../ENERGY_SCOPE_AND_SVID.md).

Local sources: [enable-audit.sh](../../chatbot/scripts/enable-audit.sh), [config.alloy](../../chatbot/observability/config.alloy), [datasources.yaml](../../chatbot/observability/datasources.yaml), [dashboard.json](../../chatbot/observability/dashboard.json).

<a id="actualizar-el-filtro-spiffe-de-una-instalación-existente"></a>

## Update the SPIFFE filter of an existing installation

The previous raw filter only included OpenAI. To also correlate Claude, update only the device dedicated to SPIFFE; keep the general audit device active. This is not needed to switch providers from the banner if the filter already includes both roles.

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=''
SPIFFE_FILTER='namespace == "verify/" and (path == "spiffe/role/lumen-openai/mintjwt" or path == "spiffe/role/lumen-anthropic/mintjwt")'
vault audit list -format=json > "$MANUAL/audit-spiffe.json"
jq -e 'has("lumen-stdout/")' "$MANUAL/audit-spiffe.json" >/dev/null
if jq -e --arg filter "$SPIFFE_FILTER" 'has("lumen-spiffe-raw/") and .["lumen-spiffe-raw/"].options.filter!=$filter' "$MANUAL/audit-spiffe.json" >/dev/null; then
  vault audit disable lumen-spiffe-raw
fi
if ! vault audit list -format=json | jq -e 'has("lumen-spiffe-raw/")' >/dev/null; then
  vault audit enable -path=lumen-spiffe-raw file \
    file_path=/proc/self/fd/2 mode=0000 log_raw=true hmac_accessor=false filter="$SPIFFE_FILTER"
fi
vault audit list -format=json | jq -e --arg filter "$SPIFFE_FILTER" \
  '.["lumen-spiffe-raw/"].options.filter==$filter'
export VAULT_NAMESPACE=verify
```
