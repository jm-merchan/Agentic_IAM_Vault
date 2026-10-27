# 12 · Blocking access and revoking credentials

[Index](README.md) · Requires [04](04-vault-iam.md); for xAI, [06](06-xai.md)

## 1. Understand where the block applies

`./demo.sh block ...` changes policies in Vault; **it does not modify the RAR inside an already signed JWT**. This chapter shows the equivalent CLI operations. The JWT can still be cryptographically valid, but Vault denies the resource because of the current policy. JWKS is neither introspection nor a per-token revocation list.

| Block | Denied paths | Already issued credentials |
|---|---|---|
| `xai` | `xai/creds/lumen`, `secrets/data/chatbot/xai-access` | Revoke xAI leases and reauthorize the cache |
| `database-read` | `database/creds/chatbot-readonly`, `chatbot-readwrite` and `chatbot-contract` | Revoke all three types: RO, RW and contracting |
| `database-write` | `database/creds/chatbot-readwrite` and `chatbot-contract` | Revoke RW and contracting leases |
| `decrypt` | Transit decrypt and Transform decode DNI/IBAN | Prevent new operations; does not erase values already revealed |

The blocks are global for these lab agents, not per user. They do not necessarily stop an SQL query or external request that is already in progress. The effects on issued credentials require revocation in addition to the deny.

## 2. Check the attached policies


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
vault read -format=json agent-registry/registration/display-name/chatbot-oidc | \
  jq '.data.ceiling_policies'
# xAI identity, prepared together with the other providers:
vault read -format=json identity/entity/name/chatbot-xai | jq '.data.policies'
```

Expected: `lumen-block-database-read`, `lumen-block-database-write`, `lumen-block-decrypt` in the OBO ceiling; `lumen-block-xai` in the policies of the autonomous xAI entity. If they are not attached, writing a policy will have no effect on those identities.

## 3. Block xAI

```bash
vault policy write lumen-block-xai - <<'HCL'
path "xai/creds/lumen" { capabilities = ["deny"] }
path "secrets/data/chatbot/xai-access" { capabilities = ["deny"] }
HCL
vault lease revoke -sync -prefix xai/creds/lumen/
```

The next message that needs the xAI model is denied by Vault, even if a key was cached: Lumen checks the authorization marker on every run. If the revocation fails, keep the deny and resolve the error/repeat the revocation; do not use `revoke-force` to pretend that an external key was removed.

To unblock, first change the cache generation and then remove the deny:

```bash
openssl rand -hex 16 | jq -Rn '{generation:input}' | vault kv put -mount=secrets chatbot/xai-access -
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-xai -
```

Select **xAI** in the banner before testing this block. OpenAI and Claude remain available: this policy blocks only xAI, not the selector or the whole conversation. A federated token that has already been issued remains subject to its expiration and the provider's controls; the SVID does not become revocable because an xAI policy was written.

## 4. Block database reads

```bash
vault policy write lumen-block-database-read - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["deny"] }
path "database/creds/chatbot-readwrite" { capabilities = ["deny"] }
path "database/creds/chatbot-contract" { capabilities = ["deny"] }
HCL
vault lease revoke -sync -prefix database/creds/chatbot-readonly/
vault lease revoke -sync -prefix database/creds/chatbot-readwrite/
vault lease revoke -sync -prefix database/creds/chatbot-contract/
```

The catalog/applications query fails when requesting credentials. Both roles are included because blocking only RO would leave SELECT available to anyone who obtains RW.

Unblock:

```bash
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-database-read -
```

## 5. Block writes only

```bash
vault policy write lumen-block-database-write - <<'HCL'
path "database/creds/chatbot-readwrite" { capabilities = ["deny"] }
path "database/creds/chatbot-contract" { capabilities = ["deny"] }
HCL
vault lease revoke -sync -prefix database/creds/chatbot-readwrite/
vault lease revoke -sync -prefix database/creds/chatbot-contract/
```

The writer can still query through RO, but saving fails. Their ability to encrypt/tokenize remains; the combination required to save is no longer complete.

Unblock:

```bash
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-database-write -
```

## 6. Block recovery of sensitive data

```bash
vault policy write lumen-block-decrypt - <<'HCL'
path "transit/decrypt/lumen-applications" { capabilities = ["deny"] }
path "transform/decode/lumen-dni" { capabilities = ["deny"] }
path "transform/decode/lumen-iban" { capabilities = ["deny"] }
path "transit/decrypt/lumen-contracts" { capabilities = ["deny"] }
path "secrets/data/lumen-contracts/*" { capabilities = ["deny"] }
HCL
```

The supervisor can still read masked versions, but a new reveal operation returns 403. PDF contracts include the DNI and IBAN in plaintext, which is why they cannot be finalized or downloaded either. There are no decryption leases to revoke; data already shown on screen cannot be withdrawn retroactively.

Unblock:

```bash
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-decrypt -
```

## 7. Demonstrate the effect on an earlier JWT

In [11](11-obo.md), obtain a valid OBO JWT for RO and keep it in `obo.json`. Without requesting another JWT, enable `lumen-block-database-read` and repeat:

```bash
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json database/creds/chatbot-readonly \
  > "$MANUAL/blocked.json" 2> "$MANUAL/blocked.log"; then
  printf 'ERROR: expected a block\n' >&2
  exit 1
fi
cat "$MANUAL/blocked.log"
```

Check for 403. Remove the deny and repeat while the JWT is still valid: that path must be allowed again if the user and the RAR allow it. A new JWT with the same RAR is also denied while the block is active.

The absence of an additional block does not grant permissions: the reader still has no RW and the writer still has no decrypt. Changing `authorization_details` when requesting a new token reduces its scope, but does not eliminate earlier tokens. Making a JWT single-use would require adding a separate consumption/replay control; that is not what is configured here.

Local sources: [block.sh](../../scripts/demo/block.sh), [access-controls.sh](../../chatbot/scripts/access-controls.sh), [explanation of the controls](../ACCESS_BLOCKS.md).

The Database and decryption blocks affect the OBO tools with any of the three models. Changing the provider does not change the user's permissions, the Vault policies or the agent's limits.

The [CIBA contracting](17-contratacion-ciba.md) extension attaches these three blocks to the JWT role `auth/ciba-contract/role/validator`. Finalization uses a native token with those policies, not the OBO ceiling. Blocking reads or writes also revokes `database/creds/chatbot-contract/`.
