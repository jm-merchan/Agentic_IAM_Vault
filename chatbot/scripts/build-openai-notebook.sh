#!/usr/bin/env bash
# Rebuild the reference notebook without outputs or credentials.
set -euo pipefail
cd "$(dirname "$0")/../.."
build=$(mktemp -d /tmp/lumen-openai-notebook.XXXXXX)
trap 'rm -rf "$build"' EXIT
printf '[]' > "$build/cells.json"
cell() {
  local kind=$1
  cat > "$build/source"
  jq --arg kind "$kind" --rawfile source "$build/source" '.+[{id:("openai-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$build/cells.json" > "$build/next"
  mv "$build/next" "$build/cells.json"
}
cell markdown <<'MD'
# OpenAI — Vault SPIFFE JWT-SVID and Workload Identity Federation

Stage-by-stage reference for Lumen's OpenAI integration. It uses **Bash, curl, jq and Vault CLI** for provisioning; the application and its tests use Python. The cells call the same scripts as `demo.sh`; you do not need to run them to start the demo.

**Flow:** Verify Client Credentials + RAR → Vault `verify/spiffe` → JWT-SVID → OpenAI token exchange → inference. Access to MySQL, Transit and Transform keeps the user's OBO. Vault issues the SPIFFE identity; this lab does not install SPIRE or implement its node/process attestation.

[Configuration and screenshots](docs/OPENAI_SPIFFE.md) · [Removal/reinstallation test](docs/E2E_OPENAI_VERIFICATION.md) · [README and common prerequisites](README.md).

Run from the workspace root with an IPython kernel that supports `%%bash`. Delivered without outputs or credentials.
MD
cell markdown <<'MD'
## 1. Prerequisites and `.env`

First complete the README prerequisites: macOS/launchd, Podman or Docker running, Minikube, kubectl, Helm 4, Vault CLI, jq, uv, a Vault license with SPIFFE/Agentic IAM/Transform and the Verify, Tavily and Oracle/MySQL integrations. For OpenAI, add ngrok, a domain from your account and an organization with access/quota for the model.

| `.env` entry | Use |
|---|---|
| `OPENAI_ADMIN_API_KEY` | Provision the project/account; also stored in `verify/secrets/openai-admin` |
| `LUMEN_MODEL_PROVIDER=auto` | Initial OpenAI selection; the banner lets you switch among the three loaded profiles |
| `LUMEN_OPENAI_MODEL=gpt-5.6-luna` | Inference model |
| `NGROK_DOMAIN=nondemanding-indistinguishably-claude.ngrok-free.dev` | Public HTTPS host of the issuer, without protocol or path |
| `NGROK_AUTHTOKEN` | Optional if ngrok is already authenticated on this machine |
| `SPIFFE_TRUST_DOMAIN=lumen.demo` | Trust domain of the SPIFFE ID |
| `OPENAI_PROJECT_ID`, `OPENAI_SERVICE_ACCOUNT_ID` | Written by `prepare-openai` |
| `OPENAI_IDENTITY_PROVIDER_ID` | ID of the provider created once in the OpenAI UI |

In OpenAI **Organization → Admin keys**, create a **Restricted → Organization Administration: Write** key, with all other categories set to **None**. Save it directly in `.env`, never in a cell. `.env` has `600` permissions and is not versioned. Do not fill in a Vault root token: the launcher generates it after initializing Vault.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
export LUMEN_PROVIDER_OVERRIDE=openai LUMEN_PREPARE_OPENAI=1
bash scripts/demo/check.sh
CODE
cell markdown <<'MD'
## 2. Prepare Vault, the public issuer and the OpenAI account

This cell also works before Vault exists. It creates/initializes Vault if missing, the `verify` namespace, the SPIFFE engine and the public documents. The administrative API creates or reuses `lumen-vault-demo` and `lumen-chatbot`; it revokes the static API key generated as a side effect of creating the account. The IDs are kept in `.env`.

| Script | Configuration |
|---|---|
| `scripts/demo/vault.sh` | Minikube, Vault TLS/Raft, init and unseal |
| `scripts/demo/bootstrap.sh` | Namespace and static integration secrets |
| `scripts/demo/spiffe.sh` | Engine, issuer, RS256, role and TTL |
| `scripts/demo/ngrok.sh` | Publishing of discovery/JWKS and check of private paths |
| `scripts/demo/openai-admin.sh` | Project/service account and revocation of the new static key |

The command does not create the WIF trust through private dashboard endpoints: that part is configured once in the official UI.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh prepare-openai
CODE
cell markdown <<'MD'
## 3. Inspect the SPIFFE configuration

Engine `verify/spiffe`; role `lumen-openai`; exact subject `spiffe://lumen.demo/ns/verify/agent/lumen-openai`; audience `https://api.openai.com/v1`; TTL **300 seconds**. `jwt_oidc_compatibility_mode=true` adds the claims OpenAI needs for validation. `use_jti_claim=true` makes it possible to correlate issuances; it does not turn the JWT into a single-use token.

The issuer is `https://<NGROK_DOMAIN>/v1/verify/spiffe`. Its URL and the SPIFFE trust domain are different concepts. The private signing key stays in Vault.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
load_vault
export VAULT_NAMESPACE=verify
vault read -format=json spiffe/config | jq '.data'
vault read -format=json spiffe/role/lumen-openai | jq '.data'
CODE
cell markdown <<'MD'
## 4. Discovery/JWKS through ngrok

The ngrok file server publishes only public Vault documents. A Bash publisher refreshes them every 30 s and withdraws the copies if Vault stops responding. It does not forward external requests to the Vault administrative API. This design works with the free domain used in the lab, without paid Traffic Policy actions.

Startup checks discovery, JWKS and HTTP 404 on secret/administration paths. `stop` stops the tunnel and the publisher. External caches may keep public documents for their TTL.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
curl -fsS --max-time 15 "https://$NGROK_DOMAIN/v1/verify/spiffe/.well-known/openid-configuration" | jq '{issuer,jwks_uri}'
curl -fsS --max-time 15 "https://$NGROK_DOMAIN/v1/verify/spiffe/.well-known/keys" | jq '{keys:[.keys[]|{kid,kty,alg,use}]}'
for path in /v1/sys/health /ui/ /v1/verify/spiffe/config /v1/verify/secrets/data/openai-admin; do
  status=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "https://$NGROK_DOMAIN$path")
  printf '%s → HTTP %s\n' "$path" "$status"
  [ "$status" = 404 ]
done
CODE
cell markdown <<'MD'
## 5. Create the provider and mapping in OpenAI — once

In [Organization → Security → Workload Identity Provider](https://platform.openai.com/settings/organization/security/workload-identity-provider):

1. Create `lumen-vault-spiffe`, type **OIDC**.
2. Issuer: the value printed by the next cell. Audience: `https://api.openai.com/v1`.
3. Use normal discovery: uncheck custom discovery and uploaded JWKS. Do not add CEL transformations.
4. Create the mapping `lumen-chatbot`, **Key `sub`**, exact value of the SPIFFE ID below, without wildcard.
5. Select the project and account already created; uncheck creating a new account.
6. **Restricted → List models: Read; Model capabilities: Request**. All other categories stay at None. They correspond to `api.model.read` and `api.model.request`; the UI also shows the count of their internal permissions.
7. Save the `idp_...` ID in `.env` as `OPENAI_IDENTITY_PROVIDER_ID`.

If the trust already exists, check it and reuse it. `remove` keeps these external resources and their IDs. When Vault is recreated, the `kid` changes; the same issuer publishes the new JWKS.

[Historical screenshot: Provider and mapping configured](docs/runs/20261015-openai-spiffe/screenshots/openai-mapping-created.jpg)
MD
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
jq -n '{issuer:("https://"+env.NGROK_DOMAIN+"/v1/verify/spiffe"),audience:"https://api.openai.com/v1",subject:("spiffe://"+(env.SPIFFE_TRUST_DOMAIN//"lumen.demo")+"/ns/verify/agent/lumen-openai"),project_id:env.OPENAI_PROJECT_ID,service_account_id:env.OPENAI_SERVICE_ACCOUNT_ID,identity_provider_id:env.OPENAI_IDENTITY_PROVIDER_ID}'
CODE
cell markdown <<'MD'
## 6. Full startup with OpenAI

Once the external prerequisites are complete, this is the only command needed. It configures MySQL/KMIP, Verify, three profiles, OBO, Transit/Transform, the autonomous identity `chatbot-openai`, the banner and observability. It restarts Lumen to load the provider; existing data and blocks are kept.

`chatbot/scripts/configure-openai.sh` configures the workload identity: Verify Client Credentials + mandatory RAR and the Vault policy that only allows `update` on `spiffe/role/lumen-openai/mintjwt`, with the OpenAI audience required. The application does not receive the Admin key. Its bootstrap token loads only runtime configuration/OAuth credentials and is revoked.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh start --provider openai
CODE
cell code <<'CODE'
%%bash
set -euo pipefail
source scripts/demo/common.sh
load_inputs
load_vault
export VAULT_NAMESPACE=verify
vault policy read chatbot-openai
vault kv get -format=json -mount=secrets chatbot/model | jq '.data.data|{provider,model,credential_source,credential_path,auth_flow,issuer,spiffe_id,audience,identity_provider_id,service_account_id}'
curl -fsS http://localhost:8088/health | jq .
CODE
cell markdown <<'MD'
## 7. Exchange and validity

On each run, [`app/spiffe.py`](chatbot/app/spiffe.py) performs:

1. Verify `POST /oauth2/token`, Client Credentials with exact RAR for `mintjwt`.
2. Vault `POST /v1/spiffe/role/lumen-openai/mintjwt`, namespace `verify`, body `{"audience":"https://api.openai.com/v1"}`. It obtains `.data.token`.
3. Validates the RS256 signature, issuer, audience, subject and expiry with Vault's public JWKS.
4. OpenAI `POST https://auth.openai.com/oauth/token`: grant `urn:ietf:params:oauth:grant-type:token-exchange`, subject type `urn:ietf:params:oauth:token-type:jwt`, JWT-SVID, provider ID and service account ID. The Admin key is not sent.
5. Uses the temporary access token as Bearer for inference.

Each run that calls the model obtains a new identity and token; a short follow-up rejected locally by the scope control does not need to call the model. OpenAI does not return a refresh token; its access token does not outlive the JWT-SVID. More than 210 s must remain before starting; maximum execution 180 s and margin 30 s. The next query repeats the exchange. There is no static fallback. The SQL credential has its own 120 s TTL and OBO flow.
MD
cell markdown <<'MD'
## 8. Automated verification

Run once `start` has finished. It checks the runtime, the application tests, MySQL/privileges/Tavily and the SPIFFE exchange with real inference. The OpenAI check requests another credential and verifies that it changes. It generates a report without tokens or keys.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh verify --provider openai
jq . chatbot/docs/openai-spiffe-verification.json
CODE
cell markdown <<'MD'
## 9. Use case walkthrough

Lumen takes the initial language from the browser and offers **EN / ES** at the top right. A saved choice takes precedence and applies to the interface and to subsequent OpenAI, xAI or Claude answers. **Continuar solicitud**, **Guardar borrador** and **Ver última traza** are the Spanish equivalents of **Continue application**, **Save draft** and **View latest trace**. Switching keeps the conversation and the form, and does not change the federation or the permissions. [Bilingual checks](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües).

Open **http://localhost:8088**, Verify login **Cloud Directory**. Look up the credentials in Vault `verify/secrets/chatbot/users/{reader,writer,supervisor}` outside the notebook.

| Profile/flow | Check |
|---|---|
| Reader | Ask about the catalog/inventory; the data is queried with SQL RO. For the catalog, the server builds the answer after a current OBO read. Creating/revealing must be denied |
| Writer | Prepare an application with the agent, complete five steps with the suggested fictitious values and save. The row contains ciphertext/tokens; revealing is denied |
| Supervisor | View the masked row and reveal it via Transit + Transform. Creating/SQL RW remains denied |
| All | «Check limits in Vault» validates nine real paths and their expected denials |
| Tavily | «A wider perspective»: independent registered agent → Vault → public search |
| Blocks | `./demo.sh block database-read`, `database-write` or `decrypt`; repeat the action and restore with `unblock` |

`block xai` controls only the xAI Secret Engine; it does not block OpenAI. Data blocks are shared. The banner shows the provider and the chosen model; the trace diagram identifies the SPIFFE issuance or the corresponding dynamic credential.
MD
cell markdown <<'MD'
## 10. Traces and auditing

In the chat, **View latest trace → View in Grafana**: `spiffe.mint_jwt_svid`, `verify.client_credentials`, `vault.write`, `openai.token_exchange`, `openai.chat`, tools and OBO. The `guardrail.energy_scope` control decides whether the query is about energy or this demo before running tools; a denial does not run the conversational agent. [Scope control and reading the JWT-SVID](docs/ENERGY_SCOPE_AND_SVID.md). Prompts/results are captured through callbacks; the model's private reasoning is not captured.

This lab's raw configuration keeps the Verify JWT and the JWT-SVID in the Vault response. In `spiffe.mint_jwt_svid`, `spiffe.jwt_svid` shows the full token and `spiffe.jwt_svid.decoded` its validated header/claims. In `openai.token_exchange`, `openai.exchange.subject_token` shows the same token sent to OpenAI. `lumen-spiffe-raw/` filters only the issuance path in `verify`; the general HMAC copy is also kept. The Admin key is not part of the runtime or of those traces.

In the Lumen viewer, selecting the arrow and clicking **Ver valores sensibles / View sensitive values** lets you inspect the values of that call. **EN / ES** translates the labels without modifying JWTs, secrets or HTTP bodies. [Viewer details](chatbot/OBSERVABILITY.md#valores-de-cada-llamada).

The next cell correlates the latest automated test with Tempo/Loki. To analyze a UI action, replace `TRACE_ID` with that action's ID. The screenshots and links in the [rebuild report](docs/E2E_OPENAI_VERIFICATION.md) identify the tested deployment.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
TRACE_ID=$(jq -er .trace_id chatbot/docs/openai-spiffe-verification.json)
LUMEN_OBSERVABILITY_REPORT=chatbot/docs/openai-observability-verification.json \
  bash chatbot/scripts/verify-observability.sh "$TRACE_ID"
CODE
cell markdown <<'MD'
## 11. Switching providers, cleanup and limits

To switch between providers that are already loaded, use the **OpenAI**, **xAI** and **Claude** buttons in the banner between queries; the conversation is kept and OIDC is not repeated. `./demo.sh start --provider openai`, `xai` or `anthropic` prepares the three integrations and sets the initial selection when there is no saved preference. That command restarts the application and requires signing in again. **EN / ES** is an independent preference and does not require restarting the process.

**Explicit cleanup, outside the notebook's routine run:** `./demo.sh remove --dry-run` shows the scope; `./demo.sh remove` deletes Vault, MySQL, observability and the Lumen resources in Verify. It erases data, signing keys and traces from the cluster. It keeps `.env`, the Verify administrative client, the OpenAI resources and the Minikube profile. `./demo.sh start` rebuilds the demo. No destructive cell is included that could run accidentally with «Run All».

Initial access to Vault uses the OAuth identity available in the lab; it is not SPIRE attestation. An issuance block does not by itself invalidate a provider access token that has already been issued. The exact mapping, the TTL and, for Claude, JTI protection limit its use. The Claude configuration is documented in `docs/manual/08-claude-spiffe.md`.

References: [OpenAI SPIFFE](https://developers.openai.com/api/docs/guides/workload-identity-federation/spiffe), [token exchange](https://developers.openai.com/api/reference/workload-identity-federation), [Vault SPIFFE](https://developer.hashicorp.com/vault/api-docs/secret/spiffe), [HashiCorp article](https://www.hashicorp.com/en/blog/implementing-workload-identity-with-hashicorp-vault-and-spiffe), [reference repo](https://github.com/DarthVaderRC/vault-spiffe).
MD
jq -n --slurpfile cells "$build/cells.json" '{nbformat:4,nbformat_minor:5,metadata:{kernelspec:{display_name:"Python 3 (IPython Bash magics)",language:"python",name:"python3"},language_info:{name:"python"}},cells:$cells[0]}' > 9_OpenAI_Vault_SPIFFE.ipynb
echo 'Notebook 9 generated, without outputs or credentials.'
