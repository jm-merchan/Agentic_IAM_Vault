# 17 · Contract a draft with CIBA

Saved applications are **drafts**. Writer can finalize one of their own
with **Contratar** (*Finalize contract*), using Modo actual (*Current mode*, called Estándar in earlier instructions) or Creación de solicitudes. The Validator confirms
in IBM Verify. Lumen presents the resulting **OAuth access JWT directly to Vault**;
only then is the protected status written to MySQL. The owning
Writer can download the PDF contract, also in later sessions.

This extension replaces the PDF approval experiment for Supervisor.
Supervisor keeps the usual reveal through OBO. There are no Control Groups.
The contract is fictitious: it is not a commercial contract or a charge.

## Prepare and enable

From the repository root, after agents, groups and MySQL, with the
[Python runtime installed](10-aplicacion.md#2-instalar-el-runtime):

```bash
bash scripts/manual/guided-run.sh bash chatbot/scripts/configure-contracts.sh
```

The wrapper loads `.env` and exports the Vault bootstrap path, also
from a new terminal. The installer keeps the selected Validator.
On this tenant it is the existing account `jose.merchan@ibm.com@www.ibm.com`
(ID `64300857U3`), which receives the request by email. Its password,
profile and administrative privileges are kept. To select another existing account:

```bash
bash scripts/manual/guided-run.sh bash chatbot/scripts/configure-contracts.sh --validator 'usuario@dominio.example'
```

Without a previous selection it prepares `lumen-validator`, with a fictitious email: **it cannot
receive an OTP by email**. Before verifying, choose a real account or configure
its authentication method in Verify. The installer does not assume mobile push.
The Validator must be separate from the demo Reader, Writer and Supervisor groups.
CIBA contracting is enabled by default after successful provisioning. Selecting a
different Validator still requires a working authentication method in Verify;
enabling the button does not approve a contract or bypass CIBA consent.
Use `configure-contracts.sh --disable` to explicitly leave contracting disabled.

The following test signs in as Writer, creates **one fictitious draft** and
sends a request to the Validator. Check the `Lumen contrato …` text before
confirming it in Verify. This script waits for the approval; it does not replace it:

```bash
bash chatbot/scripts/verify-contracts.sh
```

If it finishes successfully, it writes `chatbot/docs/contracts-verification.json`
and `$LUMEN_STATE_DIR/contracts/lumen-contrato-verificado.pdf`. This records
end-to-end evidence; it is not an activation gate. To re-enable an explicitly
disabled installation:

```bash
bash scripts/manual/guided-run.sh bash chatbot/scripts/configure-contracts.sh --enable
```

```bash
bash scripts/demo/start.sh
```

The restart ends the Lumen sessions. Sign in again. `./demo.sh start`
and the `contratacion` guided step prepare and enable the extension by default.
The inbox displays the active CIBA status. Supervisor does not receive a
contracting button: use Writer and one of Writer's own drafts.

## Verification in the interface

1. Sign in as **Writer + Modo actual** or **Writer + Creación de solicitudes**.
2. Create an application with the fictitious data and press **Guardar solicitud** (*Save application*).
3. Open **Solicitudes** (*Applications*). Only your drafts show **Contratar**.
4. Press **Contratar**. The window shows the Validator, the reference and the message
   that must match Verify. While waiting, no contract row exists.
5. The Validator authenticates and confirms in Verify. Complete **Continue** on the
   consent screen with all five requested RAR permissions selected. Authentication alone
   leaves the request pending. If they reject it or it expires, the draft is kept.
6. After the commit, **Descargar contrato PDF** (*Download contract PDF*) appears. The inbox shows
   `contratada`, the date and the download button.
7. The window shows a single link to the latest CIBA trace; when finished it is
   called **Ver traza de contratación** (*View contracting trace*). Select CIBA, the direct OAuth Vault calls, the SQL credential
   and `CALL lumen_contracts.formalize` to inspect each exchange.
8. Sign out and sign in again as the same Writer: the PDF is still available.

Closing the dialog stops the polling. **Ver contratación pendiente** (*View pending contract*) reopens it.
A pending request lives in memory for at most ten minutes; after a restart
you need to request another one. Confirmed contracts and their PDFs persist.

<a id="quién-autoriza-cada-paso"></a>

## Who authorizes each step

| Step | Identity and credential | Control |
|---|---|---|
| Read/save draft | Writer user + agent, OBO JWT | Vault applies human policies ∩ agent ceiling ∩ RAR. |
| Request CIBA | Confidential client `vault-chatbot-contract` → Verify | Lumen binds `auth_req_id` to the Writer, session agent, draft, snapshot hash and requested RAR. |
| Confirm | Validator → Verify | The client only allows CIBA; the other grants, including client_credentials, are disabled. |
| Authorize in Vault | Verify access JWT in `X-Vault-Token` | The existing `verify` OAuth profile resolves `sub` to the Validator and `actor-token.sub` to `chatbot-contract`. |
| Obtain SQL credential | Same access JWT → `database/creds/chatbot-contract` | Validator group policy ∩ CIBA actor ceiling ∩ signed RAR. |
| Finalize | Temporary SQL user → `CALL lumen_contracts.formalize` | EXECUTE only; the procedure validates the owner and snapshot, inserts and commits. |
| Publish PDF | Same access JWT → KV v2 | After the commit, exact RAR path `lumen-contracts/<Writer human entity>/<contract_id>`. |
| Cleanup | Same access JWT → `auth/token/revoke` | Revoke that JWT in Vault and its dependent SQL lease. |
| Download | Owning Writer + agent, OBO JWT | `lumen-contract-owner` policy with `{{identity.entity.id}}`, agent ceiling and read RAR. |

**CIBA uses Vault's native OAuth resource-server integration.** There is no
`auth/ciba-contract/login` call or intermediate Vault `client_token`. Verify's CIBA-only
client signs `actor-token: {"sub": "<CIBA client_id>"}` into the access JWT. This is
a fixed application claim, not an STS token exchange. Vault applies its human/actor
authorization model, using the dedicated `chatbot-contract` actor rather than Writer's session agent.
The human Validator receives `lumen-contract-confirm` through the internal group
`lumen-contract-validators`; the actor has no direct entity policies and its ceiling
includes that confirmation policy and the three administrative blocks.

Writer's normal OBO permissions stay the same. CIBA authenticates and obtains confirmation; Lumen maintains the binding
to the draft. Vault does not interpret the message text or decide which contract to
sign, and MySQL does not validate the JWT directly. Lumen validates both the ID and
access JWTs, the configured CIBA audience and exact Validator subject, the actor,
RAR constraints, freshness and `jti`. RAR comparison ignores entry order because
Verify reorders consented permissions.

### Identity and policy configuration

The installer reads the CIBA application's `providers.oidc.properties.clientId`
from Verify's management API and stores it as `chatbot/contracts.client_id` in KV.
The Validator's external ID comes from the Verify SCIM user's `id`. KV caches
these identifiers; Verify's signed claims carry them to Vault at request time.
Vault assigns the independent entity UUIDs used as alias `canonical_id`.

After loading the administrative connection in namespace `verify`, the actor setup is:

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
CLIENT_ID=$(vault kv get -mount=secrets -field=client_id chatbot/contracts)
ISSUER=https://merchan.verify.ibm.com/oauth2
vault write identity/entity/name/chatbot-contract external_id="$CLIENT_ID" policies=""
ENTITY_ID=$(vault read -field=id identity/entity/name/chatbot-contract)
vault write identity/entity-alias name=chatbot-contract canonical_id="$ENTITY_ID" \
  issuer="$ISSUER" external_id="$CLIENT_ID"
vault write agent-registry/register display_name=chatbot-contract entity_id="$ENTITY_ID" \
  ceiling_policies=lumen-contract-confirm,lumen-block-database-read,lumen-block-database-write,lumen-block-decrypt \
  no_default_ceiling_policy=true optional_authorization_details=false
```

This illustrates initial creation. For existing aliases, use the idempotent installer
above: it checks ownership and updates the same alias ID. It also creates/reconciles
the Validator's human entity and OAuth alias, attaches the internal group, and retires
only the recognized legacy `ciba-contract` auth mount. Read the deployed identities with:

```bash
vault read agent-registry/registration/display-name/chatbot-contract
vault read identity/entity/name/chatbot-contract
vault read identity/group/name/lumen-contract-validators
```

### Approval-scoped RAR

Verify accepts at most **five authorization details** per CIBA request in this tenant.
The signed list contains these five entries:

| Path | Capabilities |
|---|---|
| `transit/*` | `update` |
| `transform/decode/lumen-*` | `update` |
| `database/creds/chatbot-contract` | `read` |
| `secrets/data/lumen-contracts/<owner_entity>/<contract_id>` | `create`, `read`, `update` |
| `auth/token/revoke` | `update`, with required `token` parameter |

The two engine patterns are intersected with the **exact paths** in
`lumen-contract-confirm`; they do not permit other keys or operations. The Verify
RAR schema accepts only those two additional glob forms, alongside exact paths.
The PDF path stays exact, including during recovery of an already committed contract.
Both the OAuth profile and actor registration require RAR.

## Protected field and SQL permissions

The authoritative field is **`lumen_contracts.contracts.status = 'contratada'`**.
A separate database is used because the existing Writer role has permissions on
`scripting.*`. It cannot write to `lumen_contracts`.

The original `scripting.energy_applications` table keeps its data and its historical
status. The inbox obtains the visible status through a LEFT JOIN: without a
contract it is `borrador`; with a contract it shows the protected status. Existing drafts are not
converted automatically.

The temporary `chatbot-contract` user only receives EXECUTE on the procedure.
Its definer account is locked for login and has the read,
insert and locking permissions required. The FOR UPDATE lock also requires UPDATE;
it is limited to the identifying columns of the tables read. Those permissions
are not given to Writer or to the temporary SQL user.

The procedure locks the draft and the plan, verifies its hash and owner,
and stores the reference, requester, Validator, date, plan, hashes and encrypted PDF.
The application_id primary key makes retries idempotent. A trigger
prevents updating a contracted draft, and the FK prevents deleting it. The ordinary
credential can only read the record's public columns, not its encrypted PDF.

The PDF uses Transit `lumen-contracts` for its encrypted copy in MySQL. The
download copy in KV contains the base64-encoded PDF; KV provides encryption at rest
and per-owner ACLs. Base64 **is not encryption**. Lumen checks its SHA-256 against
MySQL on download. The logo is at the top right; the company name, CIF tax ID and headquarters are
fictitious. The content is not sent to the LLM.

## Limits, errors and recovery

- Verify's access-token lifetime is configured to 120 s. Its independently rounded
  `iat`/`exp` timestamps can differ by 121 s; Lumen permits that one-second rounding
  margin. The existing JWT expiry clock tolerance also applies. The SQL credential
  lasts 60 s by default and 120 s at most. Lumen revokes the OAuth JWT **in Vault**
  and its leases when finished; this does not revoke it at Verify or another resource server.
- Vault 2.2 does not accept OAuth JWTs on `auth/token/revoke-self`. Cleanup uses
  `auth/token/revoke` with the full JWT in `token`. The ACL requires that parameter
  and accepts JWT-shaped targets (`eyJ*`), excluding native Vault token targets.
  An actor holding another full JWT could target it too; this is not a self-only API.
  The separate [revocation lab](18-revocacion-oauth.md) demonstrates the other API:
  `auth/token/revoke-oauth` with `issuer`, `unique_id` (`jti`) and duration `exp`,
  authenticated by an operator rather than the target JWT. Both block future use
  in Vault; the contracting application continues to use the full-JWT endpoint.
- The `database-read`, `database-write` and `decrypt` blocks also limit
  the CIBA operation. The database block commands also revoke
  the corresponding SQL leases. Editing only an ACL does not revoke an SQL credential
  that has already been issued; that credential follows its lease or the token's revocation.
- The decryption block prevents preparing new contracts and new downloads. It does
  not withdraw copies already downloaded.
- Without CIBA, an ordinary ID token is rejected by the OAuth resource server, and Writer's OBO
  fails when requesting the contracting SQL role. The tests verify both.
- CIBA does not by itself produce a single-use JWT or per-row SQL authorization.
  The credential allows running the procedure during its lifetime; **Lumen**
  binds the approval to the draft and the snapshot. An operator with access to the
  lab's captured credentials can repeat calls within that
  scope. Vault/MySQL administrators are also outside this barrier.
- A change to the draft during the wait prevents finalizing the old snapshot.
  A rejection does not create a contract.
- The periodic cleanup respects a confirmation in progress; the operation checks
  expiration before finalizing and keeps the snapshot until it finishes. A
  cancellation marks the request as an error and deletes its sensitive state. If a
  commit was already in progress, refresh the inbox to learn the persisted result.
- If the commit succeeds but the KV publication fails, the contract already exists. Refresh
  the inbox, try to download and use **Recuperar PDF con CIBA** (*Recover PDF with CIBA*). The procedure
  returns the original contract and its original PDF is published, without duplicating it.
- Downloading is limited to the owning Writer; Reader and Supervisor do not get
  access to these PDFs through their role. The session is checked to still be valid and
  the same after waiting for the lock and before delivering the PDF. Supervisor keeps
  the reveal of applications.
- The trace console keeps the real requests when capture is
  enabled. Repeating a revoked credential or a consumed code returns the service's real
  error. It is not renewed automatically to simulate success.

The OAuth migration passed **13 live checks on November 3, 2026**, including direct
JWT resource access, a different PDF owner denied, native-token revocation denied,
JWT/SQL revocation, idempotent commit and two matching PDF reads.
[Migration evidence](../CIBA_OAUTH_VERIFICATION.md) also records the enabled Writer
interface and Chrome's completed PDF download. The real tests and their date are in
[contracts-verification.json](../../chatbot/docs/contracts-verification.json).
They are evidence of that run, not a guarantee about later changes.

The [October 22, 2026 rehearsal](../runs/20261022T122934Z-full-e2e/README.md) includes
a real approval using the earlier native JWT flow, nine passing checks, a single idempotent
commit and two backend downloads with the same SHA-256. Chrome showed the
persisted contract after restarting and ran its PDF button; receipt
of the file in the browser was not confirmed by the tool.

## References

- [IBM Verify SaaS: initiate CIBA](https://docs.verify.ibm.com/verify/v2.0/reference/post_oauth2-ciba).
- [OpenID CIBA Core](https://openid.net/specs/openid-client-initiated-backchannel-authentication-core-1_0.html).
- [Vault: OAuth profiles](https://developer.hashicorp.com/vault/ai/iam/concepts/oauth-profiles).
- [Vault: RAR type specification](https://developer.hashicorp.com/vault/ai/iam/reference/rar-type-specification).
- [Vault: token revocation](https://developer.hashicorp.com/vault/api-docs/auth/token).
- [MySQL: locking reads and privileges](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html).

Removing the demo includes its CIBA clients and the `chatbot-validators` group, identified by the `externalId=lumen-demo:contract-validators` marker. The real account chosen as Validator is kept. Only the fictitious `lumen-*` accounts with an `@example.invalid` email are included in the deletion inventory. The old client from the PDF experiment is disabled during migration.

## Earlier inbox capture

![Fictitious contract persisted and available in another Writer session](../screenshots/current/contract-persisted.jpg)

The [October 22 interface review](../runs/20261022T140230Z-workspace-review/README.md) checked again that the approved contract was present. It did not request a new CIBA approval: it uses the evidence from that same day's reinstallation. The tool again timed out waiting for the download event; receipt of the file in Chrome remains unconfirmed.
