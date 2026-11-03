# 18 · OAuth revocation lab in the UI and API

This lab demonstrates **delegated OBO and direct Client Credentials access**.
For each mode, token A succeeds, an operator revokes A by its issuer and unique
identifier, and A then receives HTTP 403 **before expiry**. A second token B,
with the same identity and RAR but another `jti`, still succeeds.

The delegated branch also checks that the SQL credential issued through A stops
accepting new connections before its original lease expires.

## Prerequisites and scope

- The existing Lumen installation, Vault Enterprise 2.2 and the `verify` namespace.
- The `verify` OAuth resource-server profile with `unique_id_claim=jti`.
- Existing Writer/task agents, Verify STS, the `chatbot-xai` identity and its
  `chatbot/xai-access` authorization marker. The database-read and xAI blocks must
  allow normal operation. The lab leaves existing block settings untouched.
- The Python runtime from [chapter 10](10-aplicacion.md#2-instalar-el-runtime)
  and a working MySQL port-forward on `127.0.0.1:13306`.
- For the browser walkthrough: Lumen started with the operator described in
  [chapter 10](10-aplicacion.md#3-crear-bootstrap-y-arrancar-sin-credenciales-administrativas),
  and a demo user signed in through Verify. The browser user does not need Vault's
  administrative token.
- For provisioning or running the CLI: the generated administrative connection in
  `$LUMEN_STATE_DIR/vault/config.env`.

The CLI runner creates fresh lab JWTs and a temporary operator policy/token for each
mode. It changes no business ACL, OAuth profile, agent registration or Verify client.
The direct branch reads a non-secret cache marker and performs no model call.
No CIBA approval is required.

## Demonstrate it in Lumen's UI

Open **Revocación OAuth** in the chat sidebar, or
[the revocation lab](http://localhost:8088/laboratorio-revocacion). Sign in with
Verify. The agent drawer also links to this lab alongside the RAR lab.

1. Select **Delegado · usuario + agente (OBO)**. Writer + Creación de solicitudes
   reproduces the CLI example. Other demo users can test their own effective access.
2. Click **1. Crear tokens y comprobar acceso**. The server obtains fresh A and B,
   validates their signed identities and exact RAR, then requires HTTP 200 for both.
3. Expand **Identidad de los tokens y petición de bloqueo** to show `iss`, `jti`,
   `sub`, `exp`, the delegated actor and the API JSON. Full credentials are not displayed.
4. Click **2. Bloquear token A**. The server sends the real API request using a
   separate native operator. It targets this session's A; no arbitrary token input exists.
5. Click **3. Repetir acceso con A y B**. The same A must receive 403 and B 200,
   with more than 30 seconds remaining. No new tokens are obtained at this step.
   For delegated access, a new SQL connection with A's original credential is also
   checked if its lease has not expired. A late check is labelled inconclusive for SQL.
6. Inspect the result table, trace links and **Flujo de la última acción**.
7. Select **Directo · agente (Client Credentials)** and repeat steps 2–6. This reads
   only `secrets/data/chatbot/xai-access`; it makes no model request.
8. Click **Limpiar tokens del lab** in each mode when finished. Creating another pair
   first cleans up the preceding pair in that mode. Abandoned pairs are cleaned up
   when the session expires, and on normal application shutdown.

The countdown distinguishes blocking from natural token expiry. If fewer than 30
seconds remain, create a new pair. Existing login tokens and the chat's other JWTs
are not targeted.

`chatbot/scripts/run.sh` provisions a renewable, no-default-policy operator with a
one-hour period, limited to `auth/token/revoke-oauth` for this Verify issuer plus
self-renewal/revocation. The application restricts targets to server-held pairs owned
by the current session and agent. The operator has no policy-management, token-creation
or business-data permissions. Its bearer is excluded from capture and browser payloads.
This service operator is different from the CLI runner's per-token temporary operator below.
After updating the source, `bash scripts/demo/start.sh` synchronizes the managed runtime
and prepares this operator; restarting ends current browser sessions.

[UI controller verification](../../chatbot/docs/oauth-revocation-ui-verification.json)
records the November 3 Chrome walkthrough and a subsequent live check against
Verify, Vault and MySQL using the synchronized runtime. Both modes returned A=403
and B=200 before expiry; the operator was denied other issuers, business-data
access, policy management and token creation. Test pairs were cleaned up.

| Mode | JWT identity | Resource | Vault authorization |
|---|---|---|---|
| Delegated | UI: current human and agent; CLI: Writer and task-write | `database/creds/chatbot-readonly` | Human policy ∩ actor ceiling ∩ RAR |
| Direct | `sub` = xAI client ID; no delegated actor | `secrets/data/chatbot/xai-access` | Agent entity policy ∩ RAR |

## 1. Run both modes

From the repository root:

```bash
bash chatbot/scripts/verify-oauth-revocation.sh both
```

The wrapper loads the existing connection and obtains a fresh Writer PKCE login
for the OBO branch. The two modes can also be run separately:

```bash
bash chatbot/scripts/verify-oauth-revocation.sh delegated
bash chatbot/scripts/verify-oauth-revocation.sh direct
```

The combined run writes
[oauth-revocation-verification.json](../../chatbot/docs/oauth-revocation-verification.json).
Single-mode runs write separate reports, preserving the latest combined evidence.
Only identifiers, timings, checks and trace IDs enter these reports. Full JWTs,
client secrets and SQL passwords are excluded.

## 2. Understand the API call

The endpoint is `POST /v1/auth/token/revoke-oauth`, in namespace `verify`.
The caller authenticates with a **separate operator credential**. The JSON body
identifies the target without including its full JWT:

```json
{
  "issuer": "https://merchan.verify.ibm.com/oauth2",
  "unique_id": "<token-A jti>",
  "exp": 615
}
```

- `issuer` comes from A's signed `iss` claim.
- `unique_id` comes from the claim configured by the profile's `unique_id_claim`:
  `jti` in this installation. It is the **token identifier**, separate from
  `client_id`, the human `sub`, the agent's `external_id` and Vault's entity UUID.
- The API's `exp` is a **duration in seconds**, not the JWT's epoch timestamp.
  The runner calculates remaining lifetime plus the 15-second clock tolerance.
  For an already materialized JWT, Vault uses its actual expiry when discovered.
  [API reference](https://developer.hashicorp.com/vault/api-docs/auth/token#revoke-a-jwt-oauth).

In the CLI runner, the operator receives a native Vault token with no default policy and a five-minute
maximum TTL. Its temporary policy is limited to the exact issuer and A's `jti`:

```hcl
path "auth/token/revoke-oauth" {
  capabilities = ["update"]
  required_parameters = ["issuer", "unique_id", "exp"]
  allowed_parameters = {
    "issuer" = ["https://merchan.verify.ibm.com/oauth2"]
    "unique_id" = ["<token-A jti>"]
    "exp" = []
  }
}
```

The runner substitutes the real identifiers. It first attempts to revoke B with
that operator and requires HTTP 403, then revokes A. An empty `exp` value list
allows the duration parameter; the target remains confined to A.

## 3. Send the API request manually

Use pause mode to inspect and send the request yourself:

```bash
bash chatbot/scripts/verify-oauth-revocation.sh both --pause
```

After the initial successful read, the runner prints a private directory and waits
before revoking A. In a second Bash terminal, load the connection and set
`LAB_MODE_DIR` to that exact printed directory, including `delegated` or `direct`:

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/vault/config.env"
export VAULT_ADDR VAULT_CACERT
LAB_MODE_DIR="/replace/with/the/printed/directory/delegated"
```

Inspect the non-secret target metadata and payload:

```bash
jq '{iss, jti, exp, sub}' "$LAB_MODE_DIR/claims-a.json"
cat "$LAB_MODE_DIR/revoke-a.json"
```

Send the request using the separate operator header file. The operator header
contains its native credential; the target JWT is absent from the payload:

```bash
curl --silent --show-error --cacert "$VAULT_CACERT" \
  --header "@$LAB_MODE_DIR/operator.headers" \
  --header 'Content-Type: application/json' \
  --request POST \
  --data-binary "@$LAB_MODE_DIR/revoke-a.json" \
  --output "$LAB_MODE_DIR/revoke-response.json" \
  --write-out 'Revocation HTTP %{http_code}\n' \
  "$VAULT_ADDR/v1/auth/token/revoke-oauth"
```

Probe A and B against the same resource:

```bash
RESOURCE=database/creds/chatbot-readonly
# In the direct branch, use:
# RESOURCE=secrets/data/chatbot/xai-access
for LABEL in a b; do
  curl --silent --show-error --cacert "$VAULT_CACERT" \
    --header "@$LAB_MODE_DIR/token-$LABEL.headers" \
    --output /dev/null --write-out "Token $LABEL HTTP %{http_code}\n" \
    "$VAULT_ADDR/v1/$RESOURCE"
done
```

Expected: A returns **403**, B returns **200**. Return to the runner and press Enter.
Repeating the revocation is accepted; the runner completes its checks and cleanup,
then pauses for the second mode. Continue each pause within 60 seconds. If the JWT
or original SQL lease is too close to expiry, the test fails instead of presenting
expiry as revocation. Manual SQL-role probes create additional lab leases under
the same test tokens; cleanup revokes those tokens too.

## 4. Interpret the result

| Check | Required result | Where checked |
|---|---|---|
| A reads before revocation | HTTP 200 | UI and CLI; the UI also requires initial B=200 |
| A reads after `revoke-oauth` | HTTP 403 with more than 30 seconds until JWT expiry | UI and CLI |
| A's signature and time claims | Still validate locally after revocation | UI and CLI |
| B, with the same identity and RAR | HTTP 200 | UI and CLI |
| Operator attempts to revoke B | HTTP 403 | CLI only: its temporary policy confines it to A |
| SQL login obtained through delegated A | Rejected before the original SQL lease expires | CLI required; UI checks while the lease still permits attribution |
| SQL login obtained through delegated B | Still works | CLI; the UI checks B's Vault read only |

Vault's denylist adds state to JWT acceptance. Revocation here affects **Vault**;
the lab does not call Verify's revocation endpoint or establish the token's status
at another API. It targets one `iss`/`jti` pair, not the entire user or agent.

CIBA contracting uses `auth/token/revoke` with its full access JWT at completion;
this lab demonstrates `auth/token/revoke-oauth` using a separate operator. Neither
flow uses `revoke-self` for OAuth JWT cleanup. If a normally permitted request
fails after the Mac resumes, check [the clocks](../OPERACION.md#reloj-de-la-vm)
before interpreting a 403 as evidence of blocking.
Existing SQL connections and already returned data are outside this test's scope.

On **November 3, 2026 at 11:08 CET**, the combined live run passed **20 checks**.
A still had about **599 seconds** before expiry when Vault rejected it in both
modes. The report records the precise values and trace IDs. Pause mode was also
tested by sending the documented curl requests in a second terminal: revocation
returned 200, A returned 403 and B returned 200 in both branches.

## Cleanup and evidence

The runner revokes its remaining lab JWTs, revokes the temporary operator token,
deletes the temporary policy and confirms its removal. Pause-mode header files
are private (`600`) and are removed on normal completion or handled failure.
Abrupt process termination cannot run cleanup; any remaining temporary credentials
retain their short TTLs. The runner never revokes pre-existing browser/session JWTs.

Sanitized traces and non-secret request metadata remain under
`$LUMEN_STATE_DIR/oauth-revocation/`. The four slides appended to the presentation
show separate configuration and recorded-flow views for delegated and direct access.

Sources: [runner](../../chatbot/scripts/verify-oauth-revocation.py),
[wrapper](../../chatbot/scripts/verify-oauth-revocation.sh),
[Vault token API](https://developer.hashicorp.com/vault/api-docs/auth/token#revoke-a-jwt-oauth),
[OAuth resource-server profiles](https://developer.hashicorp.com/vault/ai/iam/concepts/oauth-profiles).
