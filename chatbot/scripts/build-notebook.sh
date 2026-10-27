#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD_DIR=$(mktemp -d /tmp/lumen-notebook.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT
printf '[]' > "$BUILD_DIR/cells.json"
add_cell() {
  local kind=$1
  cat > "$BUILD_DIR/source"
  jq --arg kind "$kind" --rawfile source "$BUILD_DIR/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$BUILD_DIR/cells.json" > "$BUILD_DIR/next"
  mv "$BUILD_DIR/next" "$BUILD_DIR/cells.json"
}
add_cell markdown <<'MD'
# Lumen — chatbot with IBM Verify, Vault IAM and Deep Agents

Python/NiceGUI interface and Deep Agents with OpenAI/xAI/Claude selection. This notebook details the xAI branch (`grok-4.3`) and its dynamic Vault keys; [chapter 10](docs/manual/10-aplicacion.md) prepares the shared catalog for all three providers. It keeps OIDC Authorization Code + PKCE, MySQL through OBO and Tavily search with a registered autonomous agent. **All provisioning uses Bash, curl, jq and Vault CLI**; the application and its tests use Python. This notebook orchestrates the versioned files in `chatbot/`, which must accompany it.

The complete demo is installed with `./demo.sh`; this notebook is a stage-by-stage reference. Run it from the lab root. Do not copy passwords into cells. The notebook is delivered with empty outputs; the `chatbot/docs/*.json` reports record the real tests.

[Documentation and screenshots](chatbot/README.md) · [Database Secrets Engine](3_Database_Secret_Engine.ipynb)
MD
add_cell markdown <<'MD'
## 1. Prerequisites

Vault Enterprise with Agentic IAM enabled, `verify` namespace, `secrets/verify-admin` imported from `.env`, MySQL/KMIP and the `workshop` Kubernetes context. `./demo.sh` prepares these resources and does not depend on notebook 5. The administrative configuration is in `${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/vault/config.env`; `/tmp/vault/config.env` is the compatibility path. Required: Bash, curl, jq, Vault CLI, kubectl, OpenSSL and uv.

The Verify administrative client needs the existing permissions plus `manageUserStandardGroups` and `manageUsersPwdReset` to create/activate the users. These are not permissions of the running agent.

[Historical administrative bootstrap](verify/README.md) · [History and validation by scope](docs/manual/VALIDACION.md).
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
for cmd in bash curl jq vault kubectl openssl uv; do command -v "$cmd"; done
bash verify/scripts/configure-base.sh
kubectl --context workshop -n mysql get pod mysql-enterprise-0
CODE
add_cell markdown <<'MD'
## 2. Install the application

Isolated Python 3.12 environment in `/tmp/vault-chatbot-venv`. It can be recreated if macOS clears `/tmp`; it does not modify the `.venv` of the other notebooks.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/install.sh
CODE
add_cell markdown <<'MD'
## 3. MySQL roles

This cell creates/updates three fictitious plans and the `energy_plans`, `service_requests` and `test_encryption` tables (with three fictitious devices if empty), encrypted with InnoDB TDE. It mounts `database/` in **verify**, creates a connection with an administrator limited to `scripting` and rotates its password. Roles `chatbot-readonly` (SELECT) and `chatbot-readwrite` (SELECT, INSERT, UPDATE, DELETE), TTL 120 s and maximum 300 s. It does not run the cleanup from notebook 3.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/01-database.sh
CODE
add_cell markdown <<'MD'
## 4. OIDC applications, STS, users, agents and groups

`verify/config/oidc-template.json` is used, a template without secrets or instance ID, and dedicated resources are created: `vault-chatbot-oidc`, `vault-chatbot-research`, `vault-chatbot-sts`. Their secrets are stored in Vault.

`lumen-reader` belongs to `chatbot-readers`; `lumen-writer`, to `chatbot-writers`; `lumen-supervisor`, to `chatbot-supervisors`. They are local Cloud Directory users. Their passwords are in `verify/secrets/chatbot/users/reader`, `writer` and `supervisor`. The script activates the accounts through the API without sending emails.

Three optional identities are also prepared: Read access, Application creation and Data disclosure. They are chosen in **Task agents**, and each change starts a new session with PKCE. **Current mode** keeps the previous flow. The agent ceiling never extends the user's permissions. [Guide and limits](docs/manual/14-agentes-por-tarea.md).

The last script assigns the application to the three groups and synchronizes their members with internal Vault groups. Run it after changing memberships; restart the application and sign in again. Script 06 prepares Transit, tokenization and the additional applications table: it requires Transform in the license. See [notebook 8](8_Lumen_Protected_Applications.ipynb).
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/02-verify-apps.sh
bash chatbot/scripts/03-verify-users.sh
bash chatbot/scripts/06-data-protection.sh
bash chatbot/scripts/04-vault-agents.sh
bash chatbot/scripts/configure-task-agents.sh
bash chatbot/scripts/05-sync-groups.sh
CODE
add_cell markdown <<'MD'
## 5. Connect the model and Tavily

In Vault, namespace `verify`, KV v2 `secrets`:

- `tavily`: valid `TAVILY_API_KEY` field.
- `xai_mgmt`: management key used by the plugin from [notebook 4](4_XAI_Secret_Engine.ipynb). The chatbot cannot read it.

`./demo.sh` includes `scripts/demo/xai.sh`: `verify/xai` engine, `lumen` role with the chat/model ACLs as a JSON array and native expiry. `configure-xai.sh` creates a dedicated Verify Client Credentials client with mandatory RAR and the registered agent `chatbot-xai`, with permission for `xai/creds/lumen` and the authorization record `secrets/data/chatbot/xai-access`. Its OAuth secret is stored in `secrets/chatbot/xai`; `chatbot/model` holds configuration without an inference key. The static key `secrets/xai` stays out of the flow. Each run reauthorizes the cache through a real read in Vault. `./demo.sh block xai` installs a deny and revokes its leases; `unblock` restores access. The `database-read`, `database-write` and `decrypt` controls also exist; see `docs/ACCESS_BLOCKS.md`.

```bash
bash chatbot/scripts/configure-xai.sh
```

The application reuses the dynamic key in memory while more than 210 s remain. When it no longer covers the execution budget (180 s) plus the margin (30 s), it requests another 300 s key. The plugin does not implement renewal: a new key is obtained, without artificially extending the validity of the previous one. A lock prevents duplicate concurrent issuance. Client Credentials identifies the inference workload; OBO still applies the human's permission for MySQL and sensitive data. Provisioning preserves the existing role; it creates one with initial values only if it is missing. The dynamic xAI key is included in the Vault response captured in raw mode, per this lab's configuration.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
source verify/scripts/common.sh
bash chatbot/scripts/configure-xai.sh
for name in tavily chatbot/xai chatbot/model; do
  if vault kv metadata get -mount=secrets "$name" >/dev/null 2>&1; then
    printf '%s: exists\n' "$name"
  else
    printf '%s: pending\n' "$name"
  fi
done
CODE
add_cell markdown <<'MD'
### Verify inference, isolation and expiry

This check creates a 60 s test key, invokes Grok, checks the agent and bootstrap denials and waits for the key to expire. It may take about two minutes. It prints only results, never keys or JWTs.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/verify-xai.sh
jq '{all_passed,expired_xai_http_status,tests}' chatbot/docs/xai-dynamic-verification.json
CODE
add_cell markdown <<'MD'
## 6. Start Lumen

The next cell keeps running. Open **http://localhost:8088** in Chrome; use exactly `localhost` because of the OIDC callback. Choose Cloud Directory and one of the test users. The password can be looked up in the Vault UI.

**Request console:** at each step of a new trace, **Open request console** shows the real, editable request (URL, method, headers/token and body). It includes the LLM messages, instructions and tools, the Verify/Vault exchanges and a SQL editor for MySQL. **Send actual request** runs the call; you can also copy cURL or export to Postman. Tokens are not renewed and in-memory captures expire after ten minutes. [Usage, effects and limits](chatbot/OBSERVABILITY.md#consola-para-repetir-una-llamada-real).

**Identity in Vault:** the limits check and every trace step show the corresponding agent, with links to the registration, entity, alias and policies. The metadata is queried with a separate read-only credential and shows the query date. [Details and operation](docs/manual/14-agentes-por-tarea.md#identificar-al-agente-y-pivotar-a-vault).

**Language:** Lumen detects the browser language and offers **EN / ES** at the top right. A saved choice takes precedence, persists across sign-ins and applies to the chat, forms, traces and subsequent answers. History and captured values remain in their original language. It requires no `.env` variables or identity changes. [Usage and maintenance](chatbot/README.md#idioma-español-e-inglés).

The server listens only on loopback; it opens the MySQL port-forward 13306. It loads credentials with a five-minute Vault bootstrap token and revokes it immediately. The Python process never receives the root token.

`CHATBOT_VERIFY_ACCESS=1` runs real OBO tests when each login completes and writes reports without tokens. The inserts made by these tests are rolled back; the credentials expire in 120 s. Remove the variable for a normal run.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
CHATBOT_VERIFY_ACCESS=1 bash chatbot/scripts/run.sh
CODE
add_cell markdown <<'MD'
## 7. Test both flows

1. Sign in as `lumen-reader`: browse plans; try to prepare an application. Vault denies even an OBO token that requests the RW role.
2. Switch to `lumen-writer` (manager): complete five steps, review and save. Check «Applications», always masked. Try to reveal: Vault returns 403. Switch to `lumen-supervisor`: can reveal but cannot create or obtain SQL RW. Full walkthrough in notebook 8.
3. «A wider perspective» uses the autonomous identity `chatbot-research`: Client Credentials → Agent Registry → Tavily secret → search. It does not use the human token to obtain Tavily.
4. With a model configured: ask «Show the electricity tariffs in the Lumen catalogue». The server builds the catalog answer from a current OBO read. Run the public search in a separate query to review its sources and Tavily calls.
5. Toggle light/dark mode and check mobile. Also test **EN / ES** following the [bilingual check](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües): initial detection, persistent choice, answers in the chosen language and form preservation. In Spanish, **Solicitudes**, **Continuar solicitud** and **Usar datos de prueba** are the equivalents of **Applications**, **Continue application** and **Use test data**.

![Catalog with read-only access](docs/screenshots/current/reader-openai-catalogue.jpg)

[Historical screenshot: Dark mode](docs/runs/20261014T162141Z/screenshots/16-form-mobile-dark.jpg)

Policies authorize **SQL roles per database**, not rows. The original drafts filter by `subject_id`; the new lab inbox is shared and masked. Decryption/tokenization permissions are independent of SQL. Vault does not automatically turn the groups claim into policies: script 05 synchronizes identities.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
# Run with the server/port-forward active in another cell or terminal.
bash chatbot/scripts/test-infrastructure.sh
cd chatbot
/tmp/vault-chatbot-venv/bin/python -m pytest -q tests
for report in docs/obo-readonly.json docs/obo-readwrite.json docs/obo-supervisor.json; do
  if [ -f "$report" ]; then jq '{role,all_passed,tests}' "$report"; else echo "Pending: $report"; fi
done
CODE
add_cell markdown <<'MD'
## 8. Stopping and lab limits

Interrupt the server cell/terminal. The port-forward it opened is closed and the dynamic credentials expire. Users, apps, agents, groups and data are kept so the demo can be repeated. No automatic destructive cleanup is included.

10-minute OIDC sessions, local memory, a single process. Exposing it beyond localhost requires HTTPS, a Secure cookie, shared session storage, rate limits, workload secret management and continuous group synchronization. Do not reuse the bootstrap token as the agent's identity.
MD
jq -n --slurpfile cells "$BUILD_DIR/cells.json" '{nbformat:4,nbformat_minor:5,metadata:{kernelspec:{display_name:"Python 3 (IPython Bash magics)",language:"python",name:"python3"},language_info:{name:"python"}},cells:$cells[0]}' > 6_Lumen_Chatbot_Vault_IAM.ipynb
printf 'Notebook 6 generated.\n'
