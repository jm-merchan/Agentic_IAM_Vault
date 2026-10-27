# Blocking access during the demo

With Vault and Lumen running, run from the workspace root:

```bash
./demo.sh blocks
./demo.sh block xai
./demo.sh unblock xai
./demo.sh block database-read
./demo.sh unblock database-read
./demo.sh block database-write
./demo.sh unblock database-write
./demo.sh block decrypt
./demo.sh unblock decrypt
```

The commands use the administrative connection generated when Vault was initialized. They do not require adding secrets to `.env`, restarting the application or signing in to Verify again. The scope is Lumen in the `verify` namespace, for all its users. `unblock` removes only that additional block: group, RAR and base policy restrictions remain. Several blocks can coexist.

| Control | Paths denied in Vault | Visible effect |
|---|---|---|
| `xai` | `xai/creds/lumen`, `secrets/data/chatbot/xai-access` | A new free-form message receives an HTTP 403 from Vault before the LLM is invoked. Buttons that query data directly keep working. |
| `database-read` | `database/creds/chatbot-readonly`, `database/creds/chatbot-readwrite` and `database/creds/chatbot-contract` | Catalog, inventory, applications and contract finalization fail; leases of all three types are revoked. |
| `database-write` | `database/creds/chatbot-readwrite` and `database/creds/chatbot-contract` | The writer can still query with RO; saving drafts or finalizing contracts gets a 403 when requesting the credential. |
| `decrypt` | `transit/decrypt/lumen-applications`, `transform/decode/lumen-dni`, `transform/decode/lumen-iban`, `transit/decrypt/lumen-contracts` and `secrets/data/lumen-contracts/*` | The supervisor sees the masked list but cannot reveal the data. Contract PDFs, which contain the DNI and IBAN in clear text, can neither be finalized nor downloaded. Encryption and tokenization remain available to the writer. |

Regular access uses RO for SELECT and RW for saving drafts. Both allow reads. Contracting adds a different credential, limited to EXECUTE on the procedure; the database blocks also include this role.

## What actually changes in Vault

There are four independent policies: `lumen-block-xai`, `lumen-block-database-read`, `lumen-block-database-write` and `lumen-block-decrypt`. Normally they contain only a comment. When blocking writes, for example, the command stores in `lumen-block-database-write`:

```hcl
path "database/creds/chatbot-readwrite" {
  capabilities = ["deny"]
}
path "database/creds/chatbot-contract" {
  capabilities = ["deny"]
}
```

The `deny` takes precedence over the permission in the base policy. RAR must allow the path, but it can never override a policy denial. The JWT is not edited and there is no waiting for it to expire: new requests are evaluated against the current Vault policy. [Vault policies](https://developer.hashicorp.com/vault/docs/concepts/policies) · [RAR](https://developer.hashicorp.com/vault/ai/iam/concepts/rar/enforcement).

How the policies are attached depends on the flow:

- **CIBA contracting:** all three blocks are assigned to the native token through `auth/ciba-contract/role/validator`; this step does not use OBO.
- **Autonomous xAI:** `lumen-block-xai` is part of the policies of the `chatbot-xai` entity. This is what limits Client Credentials.
- **MySQL and OBO data protection:** all three blocks are part of the `ceiling_policies` of `chatbot-oidc` and of the task agents. Vault checks both the user's permissions and that actor limit. The registry ceiling policies apply to OBO; on their own they do not block autonomous access. [Agent registry](https://developer.hashicorp.com/vault/ai/iam/concepts/agent-registry).

`start` keeps existing block policies. `remove` deletes the demo Vault; the next `start` creates the four policies inactive. The normal-operation verifications assume there are no blocks: check `./demo.sh blocks` before running `verify`.

To inspect the policy from the CLI:

```bash
(
  source ~/.local/state/lumen-vault-demo/vault/config.env
  export VAULT_ADDR VAULT_TOKEN VAULT_CACERT
  vault policy read -namespace=verify lumen-block-database-write
  vault read -namespace=verify agent-registry/registration/display-name/chatbot-oidc
)
```

If you use `LUMEN_STATE_DIR`, replace the path in the example. In the Vault UI, select the `verify` namespace and open Policies → ACL Policies.

## RAR and cached xAI keys

Verify receives `authorization_details` in Client Credentials and returns a signed JWT with these two paths:

```json
[
  {"type":"vault:path_access","path":"xai/creds/lumen","capabilities":["read"]},
  {"type":"vault:path_access","path":"secrets/data/chatbot/xai-access","capabilities":["read"]}
]
```

Lumen validates the signature, issuer, expiry, client identity and exact RAR match. The `chatbot-xai` registration requires RAR; there is no fallback to a JWT without that restriction.

Before each run, `chatbot/xai-access` is read with that JWT. This entry contains only a cache generation, not an API key. Its ACL lets Vault also deny a run that would have reused a valid key. The key is reused as long as it covers the run's budget and the expiry margin; blocking does not require issuing a new key for every message.

`block xai` first installs the deny and synchronously revokes the `xai/creds/lumen/` leases. `unblock xai` changes the generation before removing the deny. That way, even if nobody sends a message during the block, a revoked key is not reused afterwards. A revocation failure returns an error and leaves the deny active; `revoke-force` is not used.

In the Vault 2.1.2 of this image, `/sys/capabilities-self` rejected external JWTs during testing. That is why this version uses a real KV read to reauthorize the cache, instead of presenting a capabilities check as if it had worked.

## Walkthrough in the interface

1. **xAI:** select xAI and type a question about energy. Run `block xai` and send another one: the denied path and HTTP 403 appear. Run `unblock xai` and repeat: a new key is obtained and the answer comes back.
2. **Read:** sign in as reader or writer. Open Energy plans, run `block database-read` and click the button again. After `unblock database-read`, repeat without signing out.
3. **Write:** sign in as writer and fill in a fictitious application up to Review. Run `block database-write` and click **Save draft**. Reads remain available; the INSERT never reaches MySQL. Run `unblock database-write` and retry.
4. **Decryption:** sign in as supervisor. Open Applications, run `block decrypt` and click Reveal data. The list stays masked. After `unblock decrypt`, the same operation works again.

`Check limits in Vault` makes real requests to the nine SQL/Transit/Transform paths. The Expected column describes the profile's normal permissions; an administrative block produces a deliberate difference between that column and Result.

For each action, **View latest trace → View in Grafana** lets you follow the JWT/RAR, the path and the response. During an xAI block, `xai.chat` must not appear; when blocking an SQL read, `mysql.query` must not appear. In the blocked form, the earlier SELECT that checks for duplicates may appear, but not the INSERT. The administrative changes are also recorded in the Vault audit log (`sys/policies/acl/lumen-block-*` and, where applicable, `sys/leases/revoke-prefix/*`).

## Block limits

Subsequent requests to Vault are blocked and the leases of the affected SQL/xAI paths are revoked. A request already in progress, an already open MySQL connection or information the browser has already displayed are not undone. The command does not delete the chat history or text already revealed. To check a read again, use the corresponding button: the model may remember information it received before the block.

The administrative root token is not blocked by these Lumen policies. The application does not receive that token and cannot modify the policies.

## Validation

[Real xAI test](../chatbot/docs/xai-rar-block-verification.json): JWT without RAR and with an incorrect RAR denied; same JWT allowed → blocked → allowed; a new token also denied during the block; issued lease revoked. It can be repeated with `bash chatbot/scripts/test-xai-block.sh` after exporting `VAULT_ENV_FILE` pointing to the generated connection. The test requires xAI to start unblocked and leaves it unblocked.

The [reinstallation run of 10/22](runs/20261022T122934Z-full-e2e/README.md)
and the [later full review](runs/20261022T140230Z-workspace-review/README.md)
record the results with the current installation. Check the date and scope
of each report before reusing a result.

The [run of 10/15](runs/20261015-rar-blocks/summary.json) and its
[audit correlation](runs/20261015-rar-blocks/observability.json) are kept
as history. The missing raw Loki copies observed there were fixed
in the [later rebuild that same day](E2E_OPENAI_VERIFICATION.md#trazas-y-auditoría).
It is not presented as an outstanding limitation, and its screenshots are not used as the current interface.

[CIBA contracting](manual/17-contratacion-ciba.md) uses `database/creds/chatbot-contract`. The `database-read` and `database-write` blocks include this role and revoke its leases. The CIBA JWT role also attaches the decryption block.

## Block verified in the current interface

![Supervisor denied during the decryption block](screenshots/current/decrypt-blocked.jpg)

![Same application retrieved after the block is removed](screenshots/current/supervisor-reveal-success.jpg)
