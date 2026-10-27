#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
build_dir=$(mktemp -d /tmp/lumen-oauth2c-notebook.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT
printf '[]' > "$build_dir/cells.json"
add_cell() {
  local kind=$1 id=$2
  cat > "$build_dir/source"
  jq --arg kind "$kind" --arg id "$id" --rawfile source "$build_dir/source" \
    '.+[{id:$id,cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+
    (if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' \
    "$build_dir/cells.json" > "$build_dir/next"
  mv "$build_dir/next" "$build_dir/cells.json"
}
add_cell markdown introduction <<'MD'
# 10 · Obtaining tokens with oauth2c: IBM Verify and Vault

Runnable examples for **an already installed Lumen**. `oauth2c` requests the tokens; **IBM Verify issues them**. Vault accepts the delegated JWT directly to authorize the operation, without exchanging it for another Vault token.

The walkthrough adapts HashiCorp's [token validation](https://developer.hashicorp.com/vault/ai/iam/providers/verify#step-8-validate-token-retrieval) and its [OBO exchange](https://developer.hashicorp.com/vault/ai/iam/providers/verify#step-9-validate-token-exchange) to the repository's real clients. The old URL `#step-9-validate-token-retrieval` now corresponds to step 8.

| Example | Authenticating client | Token obtained | Use |
|---|---|---|---|
| Client Credentials | `vault-chatbot-oidc` | Agent actor | `actor_token` input of the exchange |
| Authorization Code + PKCE | `vault-chatbot-oidc` + person in the browser | Human user | `subject_token` input of the exchange |
| Token Exchange + RAR | `vault-chatbot-sts` | OBO delegate | Read of `database/creds/chatbot-readonly` |
| Autonomous Client Credentials | `vault-chatbot-research` | Research agent | Identity without a user; optional RAR in its Vault registration |
| Refresh Token, conditional | OIDC client | New access token | Only if the human response contains a refresh token |

Lumen disables **ROPC** and **refresh tokens**. This notebook keeps that configuration: the last example explains and detects the unavailable case.

## Who calls whom

```text
oauth2c ── Client Credentials, Basic OIDC ───────────────> Verify /oauth2/token
        <────────────────────────────────────────────── actor token

browser ── login + consent + PKCE ───────────────────────> Verify /oauth2/authorize
        <── code at http://localhost:9876/callback ──────┘
oauth2c ── code + verifier + Basic OIDC ─────────────────> Verify /oauth2/token
        <────────────────────────────────────────────── human access token

oauth2c ── human + actor + RAR + Basic STS ─────────────> Verify /oauth2/token
        <────────────────────────────────────────────── delegated access token

Vault CLI ── delegated JWT + namespace verify ─────────> Vault /v1/database/creds/chatbot-readonly
          <──────────────────────────────────────────── temporary MySQL credential
```

The STS is a different client from the actor, even though both use the same endpoint. The Basic credential identifies the **client requesting the exchange**; `actor_token` identifies the **agent that will act**.
MD
add_cell markdown prerequisites <<'MD'
## 1. Preparation

Open this file from the repository root with the local Python/IPython kernel (`.venv`, IPython 9). The `%%bash` cells show the login URL while they wait. Run one cell at a time; the browser and the kernel must be on the same Mac.

You need the lab prepared with `./demo.sh` or the [manual](docs/manual/README.md), with Vault unsealed, MySQL running and the users/groups synchronized. The demo is not rebuilt.

Dependencies: Bash 3.2+, Vault CLI, curl, jq, OpenSSL, Python 3 and **oauth2c 1.21.1**, the version tested with these examples. If oauth2c is missing, install it from a terminal with `brew install cloudentity/tap/oauth2c` ([official source](https://github.com/SecureAuthCorp/oauth2c#installation)).

Each cell reloads `.env` and `$LUMEN_STATE_DIR/vault/config.env`; it does not depend on variables created by another cell or on `manual/session.sh`. The default state path is `~/.local/state/lumen-vault-demo`. Results are stored in its **`oauth2c/`** subdirectory, with private permissions; no tokens are stored in the repository or in KV.

The [shared helper](verify/scripts/oauth2c-common.sh) loads the environment, prepares client files and checks expiry. The commands that request the tokens remain visible in the cells.

| Existing credential in Vault, namespace `verify`, KV v2 `secrets` | Purpose |
|---|---|
| `chatbot/oidc` | Person login and actor token |
| `chatbot/sts` | Token exchange |
| `chatbot/research` | Autonomous example |
| `verify-admin` | Exclusively to add and remove the temporary callback |

`lab_credential` reads `CLIENT_ID` and `CLIENT_SECRET` from Vault for the current cell. The values are passed to the oauth2c options and are also kept in a private file for inspection; no literals are pasted into the notebook. As in the tool's own examples, secrets and tokens are passed as local process arguments. `--silent` produces JSON on stdout; `--no-browser` shows the login URL on stderr. Scopes are separated by **commas** in the CLI.
MD
add_cell code preflight <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
oauth2c version
help_text=$(oauth2c --help)
for flag in --callback-addr --rar --actor-token --requested-token-type; do
  case "$help_text" in *"$flag"*) ;; *) lab_fail "The installed version does not support $flag." ;; esac
done
for name in oidc sts research; do lab_credential "$name" "chatbot/$name"; done
printf 'Issuer: %s\nVault namespace: verify\nPrivate files: %s\n' "$ISSUER" "$LAB"
printf 'OIDC, STS and research credentials available.\n'
CODE
add_cell markdown actor-description <<'MD'
## 2. Example A: agent token with Client Credentials

It does not open a browser. The result represents `chatbot-oidc`, not a person. On its own it does not complete the delegation: this agent's registration in Vault requires RAR.

The full response is kept in `actor.json`; the claims and lifetime are shown. Repeating this cell renews the actor and discards the previous OBO token to avoid mixing runs.
MD
add_cell code actor <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/actor.json" "$LAB/obo.json"
lab_credential oidc chatbot/oidc
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type client_credentials \
  --auth-method client_secret_basic \
  --scopes openid,profile,email \
  --silent > "$WORK/actor.json"
lab_save_token actor "$WORK/actor.json"
CODE
add_cell markdown callback-description <<'MD'
## 3. Prepare the callback for the human login

This cell **adds `http://localhost:9876/callback` to `vault-chatbot-oidc` in Verify**. It keeps `http://localhost:8088/auth/callback` and the rest of its configuration. It obtains a new administrative token with oauth2c; it does not depend on `verify.headers` or on a previous administrative token.

It records whether the callback already existed. Cleanup removes it only if this notebook added it; it does not restore an old copy of the application. Do not run an application reconfiguration or another session of this notebook at the same time. It does not change grants, passwords, groups, policies or client secrets.
MD
add_cell code callback-add <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_port_free
lab_callback add
CODE
add_cell markdown human-description <<'MD'
## 4. Example B: human token with Authorization Code + PKCE

Run the cell, open the URL that appears in its output and sign in with **`lumen-reader`**. Check the selected account if Verify keeps another session. Accept the consent and let it return to the callback. The cell waits up to five minutes; do not run the next one until it finishes.

`--pkce` adds the S256 challenge and sends the verifier when redeeming the code. `oauth2c` listens only on `127.0.0.1:9876`, separate from Lumen's port 8088. There is no need to stop Lumen.

The expected result contains the human `sub`, `groups` and `may_act.client_id` equal to the OIDC client. OBO uses the **`access_token`**, not the `id_token`. Decoding a JWT lets you inspect it; it does not prove its signature or its permissions. The subsequent read against Vault verifies that the delegated token is actually accepted.
MD
add_cell code human <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/human.json" "$LAB/obo.json"
lab_port_free
lab_credential oidc chatbot/oidc
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type authorization_code \
  --auth-method client_secret_basic \
  --response-types code --response-mode query \
  --scopes openid,profile,email \
  --pkce --redirect-url "$CALLBACK" --callback-addr 127.0.0.1:9876 \
  --browser-timeout 5m --no-browser --silent > "$WORK/human.json"
client_id=$(jq -er .client_id "$LAB/oidc-client.json")
lab_claims "$WORK/human.json" | jq -e --arg cid "$client_id" \
  '.may_act.client_id==$cid and (.groups|type=="array" and length>0)' >/dev/null ||
  lab_fail 'Missing may_act or groups; check the OIDC client and the user group.'
lab_save_token human "$WORK/human.json"
CODE
add_cell markdown exchange-description <<'MD'
## 5. Example C: delegated token with Token Exchange and RAR

It uses **the STS credential**, the human token and the actor token. `--rar` sends `authorization_details`; the path is relative to the Vault namespace: **`database/creds/chatbot-readonly`**, without `verify/` or `/v1/`.

The RAR requests the **`read`** capability, even though the operation generates a dynamic credential. Vault combines the human's permissions, the agent ceiling and the RAR. Verify issuing the token does not guarantee that Vault will allow every requested path.

In Lumen, the Vault OAuth profile uses **`actor_claim=actor-token.sub`**; it must not be confused with `act.client_id`. The relationship between `sub`, `actor-token.sub` and the original claims is checked.

Tokens last about ten minutes with the installer configuration. If the login took too long, repeat A and then C; if the human token expired, repeat B and C.
MD
add_cell code exchange <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/obo.json"
lab_require_token human
lab_require_token actor
lab_credential sts chatbot/sts
RAR=$(jq -cn '[{type:"vault:path_access",path:"database/creds/chatbot-readonly",capabilities:["read"]}]')
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type urn:ietf:params:oauth:grant-type:token-exchange \
  --auth-method client_secret_basic \
  --subject-token "$(jq -er .access_token "$LAB/human.json")" \
  --subject-token-type urn:ietf:params:oauth:token-type:access_token \
  --actor-token "$(jq -er .access_token "$LAB/actor.json")" \
  --actor-token-type urn:ietf:params:oauth:token-type:access_token \
  --requested-token-type urn:ietf:params:oauth:token-type:access_token \
  --rar "$RAR" --silent > "$WORK/obo.json"
lab_claims "$WORK/obo.json" | jq -e \
  --arg subject "$(lab_claims "$LAB/human.json" | jq -er .sub)" \
  --arg actor "$(lab_claims "$LAB/actor.json" | jq -er .sub)" \
  --argjson rar "$RAR" \
  '.sub==$subject and .["actor-token"].sub==$actor and .authorization_details==$rar' >/dev/null ||
  lab_fail 'The delegated JWT does not keep the expected subject, actor or RAR.'
lab_save_token obo "$WORK/obo.json"
CODE
add_cell markdown vault-description <<'MD'
## 6. Use the delegated token against Vault

The following read **issues a temporary MySQL credential**. It does not run SQL or modify energy applications. Overriding `VAULT_TOKEN` affects only that command; the administrative credential loaded to read the bootstrap is not used to test access.

Expected result: an RO credential for reader, writer and supervisor, if the demo's additional blocks are disabled. `database.json` is kept so you can inspect the user, password and lease.
MD
add_cell code vault-positive <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_require_token obo
rm -f "$LAB/database.json"
VAULT_TOKEN=$(jq -er .access_token "$LAB/obo.json") \
  vault read -format=json database/creds/chatbot-readonly > "$WORK/database.json"
jq -e '.data.username|type=="string" and length>0' "$WORK/database.json" >/dev/null
mv "$WORK/database.json" "$LAB/database.json"
jq '{lease_id,lease_duration,renewable,username:.data.username}' "$LAB/database.json"
CODE
add_cell markdown negative-description <<'MD'
### Check a denial with the same JWT

The same token limited to RO cannot request `database/creds/chatbot-readwrite`. The cell requires **HTTP 403 / permission denied**: a TLS failure, timeout or expired token does not count as a valid test. This denial is consistent with the RAR limit; with `lumen-reader`, the human policy also denies RW. To isolate RAR, repeat the login as `lumen-writer` and check its RW permission separately in [chapter 11](docs/manual/11-obo.md).
MD
add_cell code vault-negative <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_require_token obo
if VAULT_TOKEN=$(jq -er .access_token "$LAB/obo.json") \
  vault read -format=json database/creds/chatbot-readwrite \
  > "$WORK/unexpected.json" 2> "$WORK/denied.log"; then
  lab_fail 'Vault allowed RW with a RAR limited to RO; check the profile and policies.'
fi
if grep -Eq 'Code: 403|Code:403' "$WORK/denied.log" &&
   grep -qi 'permission denied' "$WORK/denied.log"; then
  printf 'OK: Vault denied the RW path with HTTP 403.\n'
else
  lab_fail 'The failure was not the expected 403 denial. Check connectivity and expiry.'
fi
CODE
add_cell markdown autonomous-description <<'MD'
## 7. Example D: autonomous research agent

It requires neither a human login nor the STS. It issues a token with the `vault-chatbot-research` client. Its Vault registration has `optional_authorization_details=true` and a policy limited to `secrets/data/tavily`; this allows its autonomous use without RAR. It does not turn the OIDC actor into an unrestricted agent.

This cell only obtains the token and inspects its claims; it does not call Tavily or read its API key.
MD
add_cell code autonomous <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/research.json"
lab_credential research chatbot/research
oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
  --grant-type client_credentials \
  --auth-method client_secret_basic \
  --scopes openid,profile,email \
  --silent > "$WORK/research.json"
lab_save_token research "$WORK/research.json"
CODE
add_cell markdown refresh-description <<'MD'
## 8. Example E: refresh token, only if present

The Lumen installer sets `generateRefreshToken=false`. With the current configuration the cell reports **"skipped"** and does not change Verify to enable it. The complete command is included for a configuration that does issue a `refresh_token`.

A refresh token is a different credential from the access token: one cannot be substituted for the other. The renewed response is stored separately in `refreshed.json`; this notebook's OBO flow still uses `human.json`.
MD
add_cell code refresh <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
rm -f "$LAB/refreshed.json"
[ -f "$LAB/human.json" ] || lab_fail 'Run the human login first.'
if jq -e '.refresh_token|type=="string" and length>0' "$LAB/human.json" >/dev/null; then
  lab_credential oidc chatbot/oidc
  oauth2c "$ISSUER" --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" \
    --grant-type refresh_token \
    --auth-method client_secret_basic \
    --refresh-token "$(jq -er .refresh_token "$LAB/human.json")" \
    --silent > "$WORK/refreshed.json"
  lab_save_token refreshed "$WORK/refreshed.json"
else
  printf 'Refresh skipped: the human response contains no refresh_token; Lumen disables it.\n'
fi
CODE
add_cell markdown inspect-description <<'MD'
## 9. View the complete values

This cell prints the complete OAuth responses —JWT, ID token and refresh token if present— and the dynamic credentials obtained. The values are not replaced with asterisks. The outputs stay in the notebook if you save it afterwards; the delivered file is clean.

The Basic secret is in `*-client.json`. You can inspect, for example, `jq . "$LAB/oidc-client.json"` in a cell that loads the helper. The configuration JSON is not a token.
MD
add_cell code inspect <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
for name in actor human obo research refreshed database; do
  if [ -f "$LAB/$name.json" ]; then
    printf '\n=== %s ===\n' "$name"
    jq . "$LAB/$name.json"
  fi
done
CODE
add_cell markdown cleanup-description <<'MD'
## 10. Remove the temporary callback

Also run this cell if you interrupted the walkthrough after preparing the callback. It removes the 9876 URI only if this notebook added it, and keeps the other current callbacks. It keeps the private files so you can inspect them later.

JWTs expire according to `exp`; removing the callback **does not revoke them**. MySQL credentials follow the duration of their lease. To revoke them earlier, the administrative command would be `vault lease revoke "$(jq -er .lease_id "$LAB/database.json")"` after loading the helper; it is not run automatically.

When you no longer need the captures, delete only this exercise's JSON files in `$LUMEN_STATE_DIR/oauth2c/`, once the callback removal has completed. Do not delete `callback.json` before removing the callback: it records who added the URI.
MD
add_cell code callback-remove <<'CODE'
%%bash
source verify/scripts/oauth2c-common.sh
lab_callback remove
CODE
add_cell markdown troubleshooting <<'MD'
## Troubleshooting and repetition

| Symptom | Check / action |
|---|---|
| `oauth2c: command not found` | The kernel PATH must include `/opt/homebrew/bin` on Apple Silicon. Restart the kernel after installing. |
| The URL does not appear while waiting | Use the local IPython 9 kernel. Alternatively, run the cell content in Bash from the root, without the `%%bash` line. |
| Callback rejected | Repeat cell 3: the application installer may have restored Lumen's single callback. |
| Port 9876 in use | End the previous oauth2c run; do not close Lumen on 8088. |
| Lock after interrupting the kernel | Check that no other oauth2c process exists and remove only the empty `.lock` directory inside `oauth2c/`. |
| OAuth `invalid_client` / HTTP 401 | Repeat the credential read; check that OBO uses the STS client. The helper obtains another administrative token on each preparation/removal. |
| OAuth `invalid_grant` / expired token | Repeat the human login, actor token and exchange. Do not reuse an authorization code. |
| `may_act` or `groups` missing | Check the OIDC client, the user and the groups; [chapter 03](docs/manual/03-verify.md) and [04](docs/manual/04-vault-iam.md). |
| Vault 403 on the RO read | Review entities, groups, agent registration, `actor-token.sub`, RAR and the [blocks](docs/manual/12-bloqueos.md). Obtaining a JWT does not prove authorization. |
| No refresh token | This is the behavior configured in Lumen; repeat Authorization Code + PKCE. |

To repeat the walkthrough, renew the tokens in A/B/C; prepare the callback again if you removed it. The helper checks that the input tokens have the expected issuer and have not expired. It does not change permissions to turn a denial into a success.

**Validation scope:** see the [notebook report](verify/docs/oauth2c-notebook-validation.json). The local tests use the real oauth2c binary against a simulated OAuth server, with synthetic secrets. They are not equivalent to a run against your tenant or to a real test of Vault permissions.

Sources and maintenance:

- [oauth2c 1.21.1: documentation](https://github.com/SecureAuthCorp/oauth2c/tree/v1.21.1).
- [HashiCorp: IBM Verify and Agentic IAM](https://developer.hashicorp.com/vault/ai/iam/providers/verify).
- [Equivalent walkthrough with curl and Vault CLI](docs/manual/11-obo.md).
- [Generator for this notebook](verify/scripts/build-oauth2c-notebook.sh). Regenerate from the root with `bash verify/scripts/build-oauth2c-notebook.sh`; it leaves outputs and counters empty.
MD
jq -n --slurpfile cells "$build_dir/cells.json" \
  '{cells:$cells[0],metadata:{kernelspec:{display_name:"Python 3 (ipykernel)",language:"python",name:"python3"},language_info:{name:"python"}},nbformat:4,nbformat_minor:5}' \
  > 10_OAuth2c_Verify_Vault.ipynb
printf 'Generated 10_OAuth2c_Verify_Vault.ipynb\n'
