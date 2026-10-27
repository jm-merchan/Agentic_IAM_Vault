#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD_DIR=$(mktemp -d /tmp/lumen-protection-notebook.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT
printf '[]' > "$BUILD_DIR/cells.json"
add_cell() {
  local kind=$1
  cat > "$BUILD_DIR/source"
  jq --arg kind "$kind" --rawfile source "$BUILD_DIR/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$BUILD_DIR/cells.json" > "$BUILD_DIR/next"
  mv "$BUILD_DIR/next" "$BUILD_DIR/cells.json"
}
add_cell markdown <<'MD'
# Lumen — protected applications with three profiles

Protected applications reference; `./demo.sh` includes these stages. Five-step form, OBO, Transit and Transform tokenization; MySQL KMIP is kept. Provisioning with **Bash + Vault CLI + Verify API**, without Terraform or Python to configure the providers. The application remains NiceGUI/Python with Deep Agents and OpenAI/xAI/Claude selection.

Run from the repository root. Notebooks 1–6 must be prepared; the observability from notebook 7 lets you view the traces of this extension. This notebook is delivered without outputs or credentials.

[README with walkthrough and screenshots](chatbot/README.md#solicitudes-en-cinco-pasos) · [Observability](chatbot/OBSERVABILITY.md#9-solicitudes-protegidas-transit-y-transform)
MD
add_cell markdown <<'MD'
## 1. Check Vault, license and MySQL

Vault namespace **verify**, Kubernetes context **workshop**. The license must include the Transform Secrets Engine and Agentic IAM. The `Demo_Transform_Radar` project serves as a reference for Transit/Transform; its data and keys are not copied.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
source "${VAULT_ENV_FILE:-${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}/vault/config.env}"
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT VAULT_NAMESPACE=''
vault read -format=json sys/license/status | jq '.data.autoloaded | {expiration_time,features}'
export VAULT_NAMESPACE=verify
vault secrets list
kubectl --context workshop -n mysql get pod mysql-enterprise-0
CODE
add_cell markdown <<'MD'
## 2. Create the protection and the additional table

Creates `transit/keys/lumen-applications` (AES-256-GCM, non-exportable), the tokenization transformations `lumen-dni` and `lumen-iban` with roles of the same name, `convergence=false` and `mapping_mode=default`. Existing resources are reused. Creates `scripting.energy_applications` with InnoDB `ENCRYPTION='Y'`, without deleting or altering the old applications.

Name, address, contact and note are stored in an encrypted JSON. DNI and IBAN are stored as random tokens. Tariff, session identity, status, date and masked hints are clear-text metadata. KMIP tablespace encryption remains a separate, independent layer.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/06-data-protection.sh
CODE
add_cell markdown <<'MD'
## 3. Three profiles and OBO policies

| User | Verify group | SQL | Protection |
|---|---|---|---|
| lumen-reader | chatbot-readers | RO | Masked hints only |
| lumen-writer (manager) | chatbot-writers | RW | Encrypt + encode |
| lumen-supervisor | chatbot-supervisors | RO | Decrypt + decode |

Script 03 creates/activates the supervisor using the existing administrative permissions and keeps the passwords of existing users. The three passwords are in `verify`, KV `secrets`, paths `chatbot/users/{reader,writer,supervisor}`. Do not print them in cells.

04 limits the agent to eight paths: two DB credentials and six cryptographic operations. 05 synchronizes members, entities, policies and the OIDC assignment. RAR uses **read** for credentials and **update** for cryptographic operations. Restart Lumen afterwards.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/03-verify-users.sh
bash chatbot/scripts/04-vault-agents.sh
bash chatbot/scripts/05-sync-groups.sh
CODE
add_cell code <<'CODE'
%%bash
set -euo pipefail
source "${VAULT_ENV_FILE:-${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}/vault/config.env}"
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT VAULT_NAMESPACE=verify
for policy in chatbot-reader chatbot-writer chatbot-supervisor chatbot-data-ceiling; do
  printf '\nPolicy: %s\n' "$policy"
  vault policy read "$policy"
done
CODE
add_cell markdown <<'MD'
## 4. Auditing and traces

HMAC is kept in `lumen-stdout/`. The raw outputs filter the demo's four read paths and the six Transit/Transform paths in `verify/`. `lumen-protection-raw/` does not filter by operation, so that request events for denials are also kept. The paths are exact, without wildcards. The `lumen-xai-raw/` output also covers `xai/creds/lumen`.

**In this lab the user asked for raw:** traces and audit logs include JWTs, request and response bodies; also DNI/IBAN in clear text and Base64 JSON before encryption. This does not amount to confidentiality from the observability operators. Use the fictitious data button.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
LUMEN_VAULT_AUDIT_MODE=raw bash chatbot/scripts/enable-audit.sh
CODE
add_cell markdown <<'MD'
## 5. Start or restart Lumen

Stop the previous instance before running this cell. It keeps running. Open exactly **http://localhost:8088** because of the OIDC callback.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
LUMEN_TRACE_VAULT_RAW=1 bash chatbot/scripts/run.sh
CODE
add_cell markdown <<'MD'
## 6. Interactive walkthrough

The labels below are in English: select **EN** to follow them literally. **ES** switches the form, validations and inbox to Spanish; the initial language comes from the browser if no choice has been saved. **Da el siguiente paso**, **Usar datos de prueba**, **Guardar borrador** and **Revelar datos** are the Spanish equivalents of **Take the next step**, **Use test data**, **Save draft** and **Reveal data**. Switching EN/ES keeps the step and the data typed during the session, with the same permissions and the same validation of Spanish DNI/IBAN numbers. [Preservation test without saving an application](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües).

1. **Writer**: sign in as `lumen-writer`. «Take the next step» → accept the random suggestions with Tab (or «Use test data») → go through tariff, home, holder, payment and review. Try a wrong DNI letter or change the IBAN check digits: progress is blocked. Review, tick the confirmation and save.
2. **Writer**: in «Applications», click «Reveal data». The ciphertext is read with SQL RW, but Vault denies Transit decrypt with HTTP 403. Open the trace link in the dialog.
3. **Reader**: switch user from the chat to `lumen-reader`. The inbox shows hints; revealing also produces 403. Creating applications is blocked. «Check limits in Vault» denies the RW credential.
4. **Supervisor**: sign in as `lumen-supervisor` and accept the normal first-access OIDC consent. Reveal the same application: SQL RO → Transit decrypt → Transform decode DNI → Transform decode IBAN. «Hide and close» removes the dialog. Creating applications and obtaining RW remain blocked.
5. **Chat/LLM**: «Show the registered applications». The tool returns the masked projection; the form and the revealed data are not added to the prompt. Tavily keeps its separate autonomous agent.

![Review](docs/screenshots/current/form-review.jpg)
![Writer denied](docs/screenshots/current/writer-reveal-denied.jpg)
![Supervisor authorized](docs/screenshots/current/supervisor-reveal-success.jpg)

The inbox is shared **for this lab only**. SQL RO does not enforce row- or column-level security: it can read ciphertext/tokens, but Vault requires independent policies to reveal them.
MD
add_cell markdown <<'MD'
## 7. Check storage without printing clear-text data

The indicators must be `1` for the applications created through the form, including with the random suggestions. No comparison is made against old fixed sample values. This administrative check is performed directly in MySQL, outside the agent flow. It neither decrypts nor detokenizes.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
kubectl --context workshop -n mysql exec -i mysql-enterprise-0 -c mysql -- \
 sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4' <<'SQL'
SELECT application_id,
 profile_ciphertext LIKE 'vault:v1:%' AS transit_ciphertext,
 dni_token NOT REGEXP '^[0-9]{8}[A-Z]$' AS dni_token_is_opaque,
 iban_token NOT REGEXP '^ES[0-9]{22}$' AS iban_token_is_opaque,
 (SELECT ENCRYPTION='Y' FROM information_schema.innodb_tablespaces
   WHERE NAME='scripting/energy_applications') AS table_encrypted,
 dni_hint,iban_hint
FROM scripting.energy_applications;
SQL
CODE
add_cell markdown <<'MD'
## 8. Tests and correlation

The unit tests cover normalization and checksum, server-side blocking of the RO profile, protection before INSERT, failure without a partial row, retry without duplication, denied retrieval and POST capture. The JSON reports from real tests store only identifiers, sizes and booleans.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
cd chatbot
/tmp/vault-chatbot-venv/bin/python -m pytest -q tests
for report in docs/application-save-verification.json docs/application-reveal-verification.json docs/application-denials-verification.json; do
  jq '{checked_at,all_passed,traces:[.traces[]|{trace_id,span_count,raw_capture_checks}]}' "$report"
done
CODE
add_cell code <<'CODE'
%%bash
set -euo pipefail
# Replace with the ID of a new run; Tempo/Loki retain data for 7 days.
TRACE_ID=''
if [ -z "$TRACE_ID" ]; then
  echo 'Copy the Trace ID from the save/reveal link and rerun this cell.'
else
  LUMEN_OBSERVABILITY_REPORT=chatbot/docs/application-latest-verification.json \
    bash chatbot/scripts/verify-observability.sh "$TRACE_ID"
fi
CODE
add_cell markdown <<'MD'
## 9. Repetition and limits

The scripts reuse users, engines, roles and keys. There is no destructive cleanup or migration of `service_requests`; the original drafts remain under «Previous drafts». A new row is inserted only after the three protected results have been obtained. A failure after tokenization can leave token mappings without an SQL row, since there is no distributed transaction between Vault and MySQL.

For new runs without raw content: `LUMEN_VAULT_AUDIT_MODE=hmac bash chatbot/scripts/enable-audit.sh`, stop Lumen and start it with `LUMEN_TRACE_CONTENT=0 LUMEN_TRACE_VAULT_RAW=0 bash chatbot/scripts/run.sh`. This does not delete previous records.

References: [Transit](https://developer.hashicorp.com/vault/api-docs/secret/transit), [Transform](https://developer.hashicorp.com/vault/api-docs/secret/transform), [tokenization](https://developer.hashicorp.com/vault/docs/secrets/transform/tokenization), [OBO](https://developer.hashicorp.com/vault/ai/iam/setup-obo).
MD
jq -n --slurpfile cells "$BUILD_DIR/cells.json" '{nbformat:4,nbformat_minor:5,metadata:{kernelspec:{display_name:"Python 3 (IPython Bash magics)",language:"python",name:"python3"},language_info:{name:"python"}},cells:$cells[0]}' > 8_Lumen_Protected_Applications.ipynb
printf 'Notebook 8 generated.\n'
