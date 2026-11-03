# 18 · OAuth revocation lab in the UI and API

This lab demonstrates **delegated OBO and direct Client Credentials access**.
For each mode, token A succeeds, an operator revokes A by its issuer and unique
identifier, and A then receives HTTP 403 **before expiry**. A second token B,
with the same identity and RAR but another `jti`, still succeeds.

The UI also verifies **lease revocation and final-system authentication** in both
branches: delegated access issues a MySQL login; direct access issues a dynamic
xAI API key. Both credentials work before revocation. After revoking A's JWT,
its original lease must disappear and its original credential must stop authenticating
before the lease's original expiry. B's original lease and credential remain usable.

## Prerequisites and scope

- The existing Lumen installation, Vault Enterprise 2.2 and the `verify` namespace.
- The `verify` OAuth resource-server profile with `unique_id_claim=jti`.
- Existing Writer/task agents, Verify STS, the `chatbot-xai` identity, its
  `chatbot/xai-access` marker and the `xai/creds/lumen` dynamic role. The database-read and xAI blocks must
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
The original CLI runner's direct branch reads a non-secret cache marker. The UI
and the lease verifier below use dynamic xAI credentials and the authentication-only
`GET https://api.x.ai/v1/api-key` endpoint, without inference. No CIBA approval is required.

## Demonstrate it in Lumen's UI

Open **Revocación OAuth** in the chat sidebar, or
[the revocation lab](http://localhost:8088/laboratorio-revocacion). Sign in with
Verify. The agent drawer also links to this lab alongside the RAR lab.

1. Select **Delegado · usuario + agente (OBO)**. Writer + Creación de solicitudes
   reproduces the CLI example. Other demo users can test their own effective access.
2. Click **1. Crear tokens y leases**. The server obtains fresh A and B,
   validates their signed identities and exact RAR, requires HTTP 200 for both,
   and confirms each issued lease through `POST /v1/sys/leases/lookup`.
3. Click **2. Probar acceso al sistema final**. The original A and B credentials
   must both authenticate: new MySQL connections with `SELECT 1`, or xAI's API-key endpoint.
4. Expand **Leases y acceso al sistema final** and **Identidad de los tokens y
   petición de bloqueo**. They show lease IDs, initial TTLs, authentication outcomes,
   signed identity metadata and revocation JSON. Use **Ver valores sensibles / View
   sensitive values** on a new trace to inspect the workload JWT, leased credentials,
   HTTP request/response and SQL result or authentication error. Details remain in
   the owning session's server memory for ten minutes and are returned on demand.
5. Click **3. Revocar token A** while the JWTs have over 30 seconds and both leases
   over 15 seconds remaining. The server confirms both original leases are still
   active, then calls `auth/token/revoke-oauth` with the separate native operator.
   It never calls a lease-revocation endpoint. Only this session's A is targeted.
6. Click **4. Verificar token, lease y acceso**. The same JWTs must return A=403 and
   B=200 before JWT expiry. A's original lease must be absent and its original
   credential rejected before the original lease expiry. B's original lease must
   remain active and its original credential still authenticate. B's repeated Vault
   engine read creates an additional control lease, also removed during token cleanup.
7. Inspect the result table, trace links and **Flujo de la última acción**. Select
   **Directo · agente (Client Credentials)** and repeat steps 2–6 for dynamic xAI keys.
8. Click **Limpiar tokens del lab** in each mode when finished. Creating another pair
   first cleans up the preceding pair in that mode. Abandoned pairs are cleaned up
   when the session expires, and on normal application shutdown.

The countdown distinguishes blocking from natural token expiry. If fewer than 30
seconds of JWT or 15 seconds of lease remain before revocation, create a new pair.
A late final check is inconclusive, as are network failures, lookup permission
errors or a failing B control. Existing login tokens and the chat's other JWTs are not targeted.

`chatbot/scripts/run.sh` provisions a renewable, no-default-policy operator with a
one-hour period, limited to `auth/token/revoke-oauth` for this Verify issuer,
metadata lookup for `database/creds/chatbot-readonly/*` and `xai/creds/lumen/*`,
and self-renewal/revocation. It cannot list, renew or revoke leases directly.
The application restricts targets to server-held pairs owned
by the current session and agent. The operator has no policy-management, token-creation
or business-data permissions. Its bearer is excluded from capture and browser payloads.
This service operator is different from the CLI runner's per-token temporary operator below.
After updating the source, `bash scripts/demo/start.sh` synchronizes the managed runtime
and prepares this operator; restarting ends current browser sessions.

Both the embedded diagram and the trace page support detailed inspection. The
operator's request payload and response are visible, while its bearer is always
redacted and its calls cannot be replayed from the request console. Workload JWT,
xAI and SQL calls retain their original request templates. Old traces created
without detailed capture cannot recover their missing bodies; create a fresh pair.

[UI controller verification](../../chatbot/docs/oauth-revocation-ui-verification.json)
records the earlier November 3 Chrome walkthrough and a subsequent live check against
Verify, Vault and MySQL using the synchronized runtime. Both modes returned A=403
and B=200 before expiry; the operator was denied other issuers, business-data
access, policy management and token creation. Test pairs were cleaned up.

Reproduce the extended UI controller test against Verify, Vault, MySQL and xAI:

```bash
bash chatbot/scripts/verify-oauth-revocation-leases.sh
```

To also verify the real capture store and owner-only inspection endpoints:

```bash
LUMEN_REVOCATION_CAPTURE_CHECK=1 bash chatbot/scripts/verify-oauth-revocation-leases.sh
```

This writes a separate `chatbot/docs/oauth-revocation-capture-verification.json`
containing only check results and identifiers, excluding captured credentials.
The [capture verification summary](../runs/20261103-revocation-capture/README.md)
also records the browser check of xAI's HTTP 400 response body.

This verifier uses fresh JWT pairs and a five-minute native operator, with the
same policy template as the UI. It verifies both original leases disappear during
cleanup, including asynchronous xAI deletion. It excludes the administrative token
from Python. The sanitized [lease verification report](../../chatbot/docs/oauth-revocation-leases-verification.json)
records all four stages, TTLs, original lease IDs, backend results, trace IDs and
operator denials. The xAI rejection can be HTTP 400 with an explicit invalid-key
authentication error; arbitrary 400/429/5xx responses do not count as revocation.
The [extended run summary](../runs/20261103-oauth-revocation-leases/README.md)
also records the Chrome checks against the restarted application.

After the [clean reinstallation](../runs/20261103T163255Z-clean-reinstall/README.md),
the capture-enabled verifier repeated all four stages for both delegated MySQL
and direct xAI access, including original-lease revocation, final-system rejection,
the B control, operator denials and owner-only detail retrieval. Its immutable
[lease and capture report](../runs/20261103T163255Z-clean-reinstall/oauth-leases-and-captures.json)
contains the fresh evidence. That run did not repeat the Chrome trace walkthrough.

| Mode | JWT identity | Resource | Vault authorization |
|---|---|---|---|
| Delegated | UI: current human and agent; CLI: Writer and task-write | `database/creds/chatbot-readonly` | Human policy ∩ actor ceiling ∩ RAR |
| Direct | `sub` = xAI client ID; no delegated actor | UI/lease verifier: `xai/creds/lumen`; original CLI: `secrets/data/chatbot/xai-access` | Agent entity policy ∩ RAR |

## 1. Run the original CLI token lab in both modes

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
| SQL login obtained through delegated A | Rejected before the original SQL lease expires | UI, lease verifier and original CLI |
| SQL login obtained through delegated B | Still works with the original credential | UI, lease verifier and original CLI |
| Original A lease after revocation | Explicit `invalid lease` / missing response before original expiry | UI and lease verifier, both modes |
| Original B lease after revocation | Active in Vault | UI and lease verifier, both modes |
| Dynamic xAI credential obtained through direct A | Authenticates before, then rejected before original lease expiry | UI and lease verifier |
| Dynamic xAI credential obtained through direct B | Still authenticates with the original API key | UI and lease verifier |

Vault's denylist adds state to JWT acceptance. Revocation here affects **Vault**;
the lab does not call Verify's revocation endpoint or establish the token's status
at another API. It targets one `iss`/`jti` pair, not the entire user or agent.

CIBA contracting uses `auth/token/revoke` with its full access JWT at completion;
this lab demonstrates `auth/token/revoke-oauth` using a separate operator. Neither
flow uses `revoke-self` for OAuth JWT cleanup. If a normally permitted request
fails after the Mac resumes, check [the clocks](../OPERACION.md#reloj-de-la-vm)
before interpreting a 403 as evidence of blocking.
Existing SQL connections and already returned data are outside this test's scope.
Final-system revocation applies here because Vault owns the dynamic credential's
lifecycle through its secrets engine; blocking a JWT does not invalidate arbitrary
static secrets previously read from KV or revoke the Verify JWT at every service.

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
