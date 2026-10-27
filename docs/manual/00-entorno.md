# 00 · Prepare the environment and the data

[Index](README.md) · Next: [Vault](01-vault.md)

## 1. Gather the prerequisites

Tools: Bash, curl, jq, OpenSSL, Vault CLI, kubectl, Helm 4, Minikube, Podman or Docker, uv, lsof and ripgrep (`rg`) installed on the system PATH. For OpenAI and for the Claude issuer, ngrok as well. The existing launcher uses macOS/launchd; here processes run in a terminal so that every step is visible. The interactive OAuth capture uses macOS `nc` and a browser. The [scripted rehearsal](13-repeticion-script.md) uses curl and Perl (`HTML::Parser`, `JSON::PP`) for the Cloud Directory forms; it does not need a browser.

The container engine must be running. Reserve 4 CPUs and 8 GiB for Minikube and enough capacity in the engine VM. The Vault image is `josemerchan/vault-xai:2.2.0-ent`, with the xAI plugin included; no `localhost/vault-xai` image is built.

| Input | How to obtain it / usage |
|---|---|
| Vault Enterprise | License with Agentic IAM, KMIP and Transform |
| IBM Verify | Active tenant; URL in `VERIFY_TENANT` and an administrative API client (steps below) |
| Oracle Container Registry | Account with access enabled to MySQL Enterprise; accept the applicable terms beforehand |
| ripgrep (`rg`) | Required on the Bash PATH (`brew install ripgrep`). The binary embedded in Cursor/VS Code does not count |
| Tavily | API key for energy searches |
| xAI | **Management API key** able to create/revoke keys; `XAI_TEAM_ID` if the account needs it |
| OpenAI | Admin API key with Organization Administration Write, a project with quota/access to the model, permissions to configure WIF |
| Claude | Organization with API credit/access and permission to create WIF issuers, rules and service accounts |
| ngrok, for SPIFFE | Stable domain owned by your account; OpenAI reads discovery/JWKS and Claude uses it as the exact issuer |
| Lab passwords | MySQL root and the reader, writer and supervisor users |

<a id="cliente-api-administrativo-en-ibm-verify"></a>
### Administrative API client in IBM Verify

This client is the **provisioning bootstrap**: chapter [03](03-verify.md) uses it with Client Credentials to create the OIDC/STS applications, the RAR type, and the Lumen users and groups. It is not the human login app nor the OBO STS; the lab creates those later. The running agents do **not** receive these permissions.

1. Go to the tenant administration console. Typical URL: `https://<tenant>.verify.ibm.com/ui/admin` (or the **Admin** link from the portal). You need a tenant administrator user.
2. Open **Security → API access → API clients**. In the Spanish UI it usually appears as **Seguridad → Acceso de API** (sometimes under Configuration). IBM guide: [Creating API clients](https://www.ibm.com/docs/en/security-verify?topic=access-creating-api-clients).
3. **Add API client** / Añadir cliente API.
4. In the authorizations step (*Entitlements*), check exactly these six (the visible names may be translated; the technical identifier is the one in the left column):

| Entitlement | What this demo uses it for |
|---|---|
| `manageAppAccessAdmin` | Create/update OIDC applications (`vault-chatbot-*`) |
| `manageAuthDetailTypes` | Register the RAR type `vault:path_access` |
| `manageSTSClients` | Create the token exchange (OBO) STS client |
| `readUsers` | Read SCIM users while configuring identities |
| `manageUserStandardGroups` | Create and assign the `chatbot-readers` / `chatbot-writers` / `chatbot-supervisors` groups |
| `manageUsersPwdReset` | Set the final password of the lab users |

5. Continue the wizard. Leave population/group restrictions at their defaults (without limiting to subsets) unless your tenant requires otherwise: with `manageUserStandardGroups` Verify may reject certain group restrictions.
6. In credentials, leave the client authentication method at its default (*Client secret*). Give it a recognizable name, e.g. `lumen-vault-admin` or `vault-verify-automation`.
7. **Save**. Immediately copy the **Client ID** and the **Client secret** (the secret is usually shown only once) to `VERIFY_ADMIN_CLIENT_ID` and `VERIFY_ADMIN_CLIENT_SECRET` in `.env`.
8. `VERIFY_TENANT` is the tenant base URL, for example `https://merchan.verify.ibm.com`: **without** `-admin`, **without** `/ui/admin` and **without** a trailing slash. The OIDC discovery (`/oauth2/.well-known/openid-configuration`) must respond at that base; it is checked in section 4.

If the tenant already has a client with those six entitlements, reuse it: there is no need to create another one. The demo's `remove` **keeps** this administrative client and the shared RAR schema.

## 2. Define names and external secrets

| Item | Demo value |
|---|---|
| Minikube profile/context | `workshop` |
| Kubernetes namespaces | `vault`, `mysql`, `lumen-observability` |
| Vault namespace | `verify` |
| Local Vault | `https://127.0.0.1:8443` |
| Application / callback | `http://localhost:8088` / `http://localhost:8088/auth/callback` |
| Local MySQL | `127.0.0.1:13306`, database `scripting` |
| Grafana | `http://localhost:3000` |
| SPIFFE trust domain | `lumen.demo` |

From the workspace root, open Bash and prepare `.env` without replacing an existing one. The file is stored next to the local state, outside the workspace, because the workspace may be in a synced folder:

```bash
bash
set +x
umask 077
export LUMEN_STATE_DIR="${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}"
export DEMO_ENV_FILE="${DEMO_ENV_FILE:-$LUMEN_STATE_DIR/.env}"
mkdir -p "$LUMEN_STATE_DIR"
chmod 700 "$LUMEN_STATE_DIR"
if [ ! -f "$DEMO_ENV_FILE" ] && [ -f .env ]; then mv .env "$DEMO_ENV_FILE"; fi
if [ ! -f "$DEMO_ENV_FILE" ]; then cp .env.example "$DEMO_ENV_FILE"; fi
chmod 600 "$DEMO_ENV_FILE"
printf 'Edit: %s\n' "$DEMO_ENV_FILE"
```

Edit that `.env` following [the complete template](../../.env.example). Fill in `VERIFY_TENANT`, `VERIFY_ADMIN_CLIENT_ID`, `VERIFY_ADMIN_CLIENT_SECRET`, `TAVILY_API_KEY`, `ORACLE_REG_EMAIL`, `ORACLE_REG_PASSWORD`, `VAULT_LICENSE`, `MYSQL_ROOT_PASSWORD` and the three `LUMEN_*_PASSWORD`.

For xAI add `XAI_MANAGEMENT_API_KEY`; for OpenAI `OPENAI_ADMIN_API_KEY`, `NGROK_DOMAIN` and, if there is no local authentication, `NGROK_AUTHTOKEN`. The three OpenAI IDs are obtained in chapter 07. For Claude, chapter 08 obtains the five WIF IDs and does not request an API key. This demo's domain is `nondemanding-indistinguishably-claude.ngrok-free.dev`; another account must use its own domain. Values use Bash syntax, quoted where appropriate.

The three providers are prerequisites of the selector. Keep `LUMEN_MODEL_PROVIDER=auto` and the template's basic models: `LUMEN_OPENAI_MODEL=gpt-5.6-luna`, `LUMEN_XAI_MODEL=grok-4.3` and `LUMEN_ANTHROPIC_MODEL=claude-haiku-5-5`. The initial provider does not exclude the other integrations. In a new manual installation the WIF IDs are filled in when you reach 07–08; the automatic rehearsal requires them to be saved already, before removing resources.

**Do not put `VAULT_TOKEN`, `VAULT_ADDR` or `VAULT_CACERT` in `.env`.** Vault may not exist yet. Its private configuration is generated after `operator init`.

<a id="3-crear-una-sesión-de-trabajo-reutilizable"></a>
## 3. Create a reusable working session

```bash
export LUMEN_ROOT="$PWD"
export LUMEN_STATE_DIR="${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}"
export DEMO_ENV_FILE="${DEMO_ENV_FILE:-$LUMEN_STATE_DIR/.env}"
export MANUAL="$LUMEN_STATE_DIR/manual"
mkdir -p "$MANUAL" "$LUMEN_STATE_DIR/vault"
chmod 700 "$MANUAL" "$LUMEN_STATE_DIR/vault"
{
  printf 'export LUMEN_ROOT=%q\n' "$LUMEN_ROOT"
  printf 'export LUMEN_STATE_DIR=%q\n' "$LUMEN_STATE_DIR"
  printf 'export DEMO_ENV_FILE=%q\n' "$DEMO_ENV_FILE"
  cat <<'BASH'
set +x
set -euo pipefail
umask 077
set -a
source "$DEMO_ENV_FILE"
set +a
export MANUAL="$LUMEN_STATE_DIR/manual"
export VAULT_ENV_FILE="$LUMEN_STATE_DIR/vault/config.env"
export TENANT="${VERIFY_TENANT%/}"
K=(kubectl --context workshop)
cd "$LUMEN_ROOT"
form_encode() {
  jq -jr 'to_entries|map((.key|@uri)+"="+(.value|tostring|@uri))|join("&")'
}
BASH
} > "$MANUAL/session.sh"
source "$MANUAL/session.sh"
```

After the `source` above, this same terminal already has the session. **Do not load `session.sh` in zsh** (prompt `❯`): it enables `set -e` in the login shell and a single failure closes the terminal. In a new terminal:

```bash
bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
```

The prompt must be `bash-…$` or similar, not `❯`. Every chapter reminds you how to do it. With `set -euo pipefail`, a failing command terminates that Bash and you return to the parent zsh; the Terminal app is not lost. JSON files with tokens/passwords stay in `$MANUAL`; the public SPIFFE documents will be stored in another directory, which must never include this material.

## 4. Check tools and connectivity

Confirm Bash + session. If `$MANUAL` is empty, the discovery redirect tries to write `/verify-discovery.json` and fails with *read-only file system*.

```bash
if [ -z "${BASH_VERSION:-}" ]; then
  printf 'Enter Bash first: bash && source …/manual/session.sh\n' >&2
else
  : "${MANUAL:?Load session.sh before continuing}"
  : "${TENANT:?VERIFY_TENANT is empty in .env}"
  printf 'MANUAL=%s\nTENANT=%s\n' "$MANUAL" "$TENANT"
fi
```

Inventory and discovery. `set +e` is left on for the whole block to list missing items and network errors **without exiting the shell**; at the end `set -e` is restored only if everything went well.

```bash
set +e
missing=0
for tool in curl jq openssl vault kubectl helm minikube uv lsof rg nc perl ngrok; do
  if ! command -v "$tool"; then
    printf 'Missing: %s\n' "$tool" >&2
    missing=1
  fi
done
perl -MHTML::Parser -MJSON::PP -e 1 || {
  printf 'Missing: Perl HTML::Parser or JSON::PP\n' >&2
  missing=1
}
"${CONTAINER_ENGINE:-podman}" info >/dev/null || {
  printf 'Start Podman/Docker (CONTAINER_ENGINE=%s)\n' "${CONTAINER_ENGINE:-podman}" >&2
  missing=1
}
if [ "$missing" -ne 0 ]; then
  printf 'Fix the above and run this block again. The session is still active.\n' >&2
elif ! curl --fail --silent --show-error \
  "$TENANT/oauth2/.well-known/openid-configuration" \
  > "$MANUAL/verify-discovery.json"; then
  printf 'Verify discovery failed (TENANT=%s).\n' "$TENANT" >&2
else
  jq '{issuer,authorization_endpoint,token_endpoint,jwks_uri}' \
    "$MANUAL/verify-discovery.json"
  set -e
fi
```

Expected result: endpoints of the correct tenant. This read does not yet prove that the administrative client has permissions; that is checked when authenticating and calling the API in chapter 03. Use the tenant hostname, without `-admin` or `/ui/admin`.
