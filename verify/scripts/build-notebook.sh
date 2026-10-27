#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build_dir=$(mktemp -d /tmp/verify-notebook.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT
printf '[]' > "$build_dir/cells.json"
add_cell() {
  local kind=$1
  cat > "$build_dir/source"
  jq --arg kind "$kind" --rawfile source "$build_dir/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$build_dir/cells.json" > "$build_dir/next"
  mv "$build_dir/next" "$build_dir/cells.json"
}
add_cell markdown <<'MD'
# IBM Verify + Vault Agentic IAM and OBO — Bash / API

This notebook keeps the base `verify-agent` exercise; the full Lumen demo is started with `./demo.sh` and does not need its saved human session. This exercise configures the existing `merchan.verify.ibm.com` lab and Vault `https://127.0.0.1:8443`, **exclusively in the `verify` namespace**. All code cells use Bash (`%%bash`); the IPython kernel only runs that magic. There are no Python scripts.

The administrative client was created once in the UI because there were no administrative API credentials yet. Everything else is configured with `curl`, `jq` and the Vault CLI. `vault-authn-entry` is reused; it is not recreated and its secret is not regenerated.

## Verified status

Configuration applied and scripts run against the tenant and Vault. The autonomous and OBO tests are collected at the end. The cells contain no tokens or passwords, and their outputs are delivered clean. The run report is independent of the Jupyter counters.

The human authenticates with Authorization Code + PKCE; the actor uses the Client Credentials of `vault-authn-entry`. The STS exchanges both tokens and adds RAR. Vault validates the JWT on every request, without creating an intermediate Vault token.
MD
add_cell markdown <<'MD'
## 1. Prerequisites and bootstrap

Open the notebook with the project's `.venv`/Python 3 kernel. Run it from the project root or from `verify/`. Requires Bash 3.2+, `curl`, `jq`, `vault`, `openssl` and `nc` (local callback on macOS). Vault must be reachable and unsealed; `/tmp/vault/config.env` contains `VAULT_ADDR`, `VAULT_TOKEN` and `VAULT_CACERT`.

The following already exist in the `verify` namespace, KV v2 engine `secrets/`:

| Path | Use |
|---|---|
| `verify` | The application's OAuth client, with `client_id` and `client_secret` |
| `verify-admin` | The `vault-verify-automation` client, with `client_id`, `client_secret` and `tenant` |

For another tenant, the code must be adapted explicitly and the bootstrap created under **Security → API access**. Permissions: `manageAppAccessAdmin`, `manageSTSClients`, `manageAuthDetailTypes` and `readUsers`. The last one checks the subject in the directory. Store the credential in Vault; do not enter it in a cell or its outputs.

![API client with four permissions](docs/screenshots/09-api-automation-client.jpg)
MD
add_cell markdown <<'MD'
## 2. Shared scripts

The workspace scripts are the implementation source. This notebook does not overwrite them with embedded copies, to avoid restoring old versions after a review.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify ]; then cd verify; fi
for file in scripts/0*.sh scripts/common.sh scripts/configure-base.sh; do bash -n "$file"; done
CODE
add_cell markdown <<'MD'
## 3. Verify connectivity and inventory

This stage does not change resources. It checks the Vault CA, the namespace, the KV engine, the credentials and the administrative APIs. The inventory prints only resource identifiers and names.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/00-preflight.sh
bash scripts/01-inventory.sh
CODE
add_cell markdown <<'MD'
## 4. Configure Verify through the API

The existing application is located by name and updated while preserving its configuration and credential. JWT, Code/query, a confidential client with Basic, PKCE and `may_act.client_id` are set.

`vault:path_access` is created with a path/capabilities schema and its content is checked. The consent text must be sent base64-encoded: this is a Verify API requirement. `vault-obo-sts` is created or updated; it requires an actor token, issues 600-second JWTs and receives no Verify administrative permissions.

STS introspection uses `name` (not `targetName`) and the custom rule `{"sub":requestContext["actor_token"].sub}` for `actor-token`. The API rejects `sourceId` when a custom rule is used.

The STS credential is stored in `secrets/verify-sts`; the resource IDs, in `secrets/verify-config`. Rerunning reuses the existing application, RAR type and STS.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/02-configure-verify.sh
CODE
add_cell markdown <<'MD'
![STS created through the API](docs/screenshots/10-sts-created-api.jpg)

![RAR type created through the API](docs/screenshots/11-rar-created-api.jpg)

## 5. Obtain a human token with PKCE

This cell displays an authorization URL and waits up to ten minutes. Open it in Chrome and complete IBMid and the consent. If IBMid first takes you to the dashboard, open the same URL again while the cell is still waiting. The callback uses `http://localhost:9876/callback` and `nc` listens only on `127.0.0.1`.

The cell checks `state`, exchanges the code with the PKCE verifier, checks issuer, expiry and `may_act`, and stores the result in `secrets/verify-human-session`. It never prints JWTs. Local decoding does not verify the signature: Vault does that when testing access.

If another process is listening on 9876, close it first. Do not launch two runs of this stage at the same time. The human credential expires: repeat this cell when needed.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/03-human-login.sh
CODE
add_cell markdown <<'MD'
## 6. Configure Vault in verify

The `verify` OAuth profile, the `verify-human` and `verify-agent` entities, their aliases and the policies are created or updated. The human ID is checked against the Verify directory and the `sub` of the Client Credentials token is used for the agent.

**Required adjustment verified in this lab:** `actor_claim="actor-token.sub"`. The default `act.sub` does not identify the actor of these JWTs, whose `act` contains `client_id`. The RAR path is `secrets/data/agentic-demo/shared`, relative to the namespace; it does not carry the `verify/` prefix.

Following the STS limitation described by HashiCorp, this profile does not configure `audiences`; it validates issuer, JWKS, RS256 and the registered identities. The profile requires RAR; only this agent's registration has `optional_authorization_details=true` to allow its autonomous Client Credentials flow. When RAR is included, it is still restrictive.

The agent can only read `shared`. The human can read `shared` and `human-only`. Delegation must respect the intersection of the human policy, the agent ceiling and RAR. No demo policy allows reading bootstrap credentials.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/04-configure-vault.sh
CODE
add_cell markdown <<'MD'
![Agent registered in verify](docs/screenshots/12-vault-agent-registry.jpg)

## 7. Token Exchange and authorization tests

A new actor token is obtained, exchanged together with the human token at the STS, and the claims structure is validated. The delegated token is stored in `secrets/verify-delegated-session`. Direct requests to Vault use the JWT and `X-Vault-Namespace: verify`.

Positive and negative access is tested. Two additional tests isolate the agent ceiling and RAR, so that an HTTP 403 is not simply taken as evidence that the JWT works. The positive read proves that Vault accepted the signature and identities.

The public report `docs/api-verification.json` contains only the date, results and HTTP statuses. If any check fails, the script exits with an error and does not replace the previous successful report; always check its date.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
if [ -d verify/scripts ]; then cd verify; fi
bash scripts/05-test-access.sh
jq . docs/api-verification.json
CODE
add_cell markdown <<'MD'
## 8. Repeat the demonstration

For another demonstration, run stage 5 to renew the human token and stage 7 to generate a new delegated token and test access. The configuration stages can be repeated without duplicating lab resources; they update the objects managed by these scripts. The KV engine keeps versions of the credentials and sessions.

This notebook starts from the existing tenant and application. It does not create an IBM Verify account, does not modify the Minikube deployment and does not touch the archived Okta material. ROPC was enabled during the initial lab setup, but these scripts do not use it.

References:

- [HashiCorp: IBM Verify](https://developer.hashicorp.com/vault/ai/iam/providers/verify)
- [HashiCorp: OBO](https://developer.hashicorp.com/vault/ai/iam/setup-obo)
- [HashiCorp: OAuth profile and actor_claim](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server)
- [HashiCorp: optional RAR](https://developer.hashicorp.com/vault/ai/iam/make-rar-optional)
- [IBM: Applications API](https://docs.verify.ibm.com/verify/reference/updateapplication)
- [IBM: STS API](https://docs.verify.ibm.com/verify/reference/createstsclient)
- [IBM: RAR types API](https://docs.verify.ibm.com/verify/reference/createauthdetailtype)
MD
jq -n --slurpfile cells "$build_dir/cells.json" '{cells:($cells[0]|to_entries|map(.value+{id:("verify-cell-"+(.key|tostring))})),metadata:{kernelspec:{display_name:"Python 3 (Bash cells)",language:"python",name:"python3"},language_info:{name:"python"}},nbformat:4,nbformat_minor:5}' > 5_IBM_Verify_Vault_Agentic_IAM_Bash.ipynb
printf 'Notebook generated: verify/5_IBM_Verify_Vault_Agentic_IAM_Bash.ipynb\n'
