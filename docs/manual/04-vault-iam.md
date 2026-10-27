# 04 · OAuth profile, identities, groups and agents in Vault

[Index](README.md) · Requires [03](03-verify.md) · Next: [Protection](05-proteccion.md)

**Guided run:** the `agentes` step of the [step-by-step script](PASO-A-PASO.md) checks OIDC and research before configuring entities and registrations; the following `grupos` step synchronizes the user ACLs. To resume after earlier Verify failures, start with `bash scripts/manual/paso-a-paso.sh desde verify-base`.

## 1. Configure the Verify OAuth profile


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
jq -n --arg issuer "$TENANT/oauth2" '{
  issuer_id:$issuer,jwks_uri:($issuer+"/jwks"),use_jwks:true,
  user_claim:"sub",actor_claim:"actor-token.sub",supported_algorithms:["RS256"],
  jwt_type:"access_token",clock_skew_leeway:15,
  no_default_policy:true,optional_authorization_details:false
}' | vault write sys/config/oauth-resource-server/verify -
vault read sys/config/oauth-resource-server/verify
```

`auth/jwt` is not enabled: Agentic IAM accepts the OAuth JWT directly in the resource operations. The profile interprets `sub` as the user/identity and `actor-token.sub` as the actor in OBO. `audiences` is omitted because of the Verify STS limitation documented for this flow; do not extrapolate that decision to other issuers. [Verify reference](https://developer.hashicorp.com/vault/ai/iam/providers/verify).

The `use_jwks=true` mode validates the signature and claims with the public keys obtained by Vault. **It does not introspect the token at Verify on every request**; JWKS may be cached. The JWT is not single-use. Vault applies its policies and RAR again when accessing the resource. [Validation modes](https://developer.hashicorp.com/vault/ai/iam/concepts/oauth-profiles#key-validation-modes).

## 2. Write the application policies

| Policy | Permissions |
|---|---|
| `chatbot-reader` | Issue RO SQL |
| `chatbot-writer` | RO/RW SQL, Transit encrypt, Transform encode |
| `chatbot-supervisor` | RO SQL, Transit decrypt, Transform decode |
| `chatbot-data-ceiling` | Ceiling of the OBO actor: union of the paths above |
| `chatbot-research` | Read Tavily only |

The groups are independent. A user in several groups may accumulate permissions; for the demo, each account belongs to one of the three Lumen groups.

```bash
vault policy write chatbot-data-ceiling - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
HCL
```

```bash
vault policy write chatbot-reader - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
HCL
```

```bash
vault policy write chatbot-writer - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
HCL
```

```bash
vault policy write chatbot-supervisor - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
HCL
```

```bash
vault policy write chatbot-research - <<'HCL'
path "secrets/data/tavily" { capabilities = ["read"] }
HCL
```

Also create the empty policies where the blocks will be activated. They grant no permission and must not be emptied if a block was already active:

```bash
vault policy list -format=json > "$MANUAL/policies.json"
for target in xai database-read database-write decrypt; do
  if ! jq -e --arg p "lumen-block-$target" 'index($p)!=null' "$MANUAL/policies.json" >/dev/null; then
    printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write "lumen-block-$target" -
  fi
done
```

## 3. Create entities and aliases for the agents

The Verify `client_id` is the `sub` of the Client Credentials token. No human user is created for each agent. In OBO, the human entity and the `chatbot-oidc` entity are distinguished.

Run each block separately, waiting for `bash-3.2$` to return. If the terminal still shows `>` after pasting a complete block, press **Ctrl+C** and copy that block again. If Bash exits and `❯` reappears, enter with `bash` and load the session from step 1 before continuing.

First check that chapter 03 has saved the credentials of **both** applications. This check does not modify entities or show credentials:

```bash
vault kv get -mount=secrets -field=client_id chatbot/oidc >/dev/null && vault kv get -mount=secrets -field=client_id chatbot/research >/dev/null
```

If `chatbot/research` is missing, go back to [03, step 3](03-verify.md#3-create-the-oidc-and-research-applications), select `suffix=research` and complete its configuration until the credential is saved in Vault. A local file from a previous run does not prove that the application still exists.

Configure one agent per pass. Start with `oidc`; when finished, repeat from here changing the following line to `suffix=research`:

```bash
suffix=oidc
```

Build the agent name:

```bash
name="chatbot-$suffix"
```

Get its client ID from Vault:

```bash
cid=$(vault kv get -mount=secrets -field=client_id "chatbot/$suffix")
```

Select its policy and the RAR requirement. **Copy this whole block:**

```bash
case "$suffix" in
  oidc) policy=chatbot-data-ceiling; optional=false; entity_policies='' ;;
  research) policy=chatbot-research; optional=true; entity_policies=$policy ;;
  *) printf 'The agent must be oidc or research\n' >&2; false ;;
esac
```

Create or update the entity. `chatbot-oidc` only acts on behalf of a user: its ceiling limits that person's policies and the entity receives no policies of its own. `chatbot-research` acts autonomously and keeps its own:

```bash
vault write "identity/entity/name/$name" external_id="$cid" policies="$entity_policies"
```

Get the entity ID:

```bash
entity=$(vault read -field=id "identity/entity/name/$name")
```

Query the current aliases:

```bash
vault read -format=json "identity/entity/id/$entity" > "$MANUAL/agent-entity.json"
```

Look up the alias by name and stop if there are duplicates:

```bash
alias_id=$(jq -r --arg name "$name" '[.data.aliases[]?|select(.name==$name)|.id]|if length>1 then error("Duplicate alias") else .[0]//empty end' "$MANUAL/agent-entity.json")
```

Create the alias only if it is missing. **Copy the whole conditional:**

```bash
if [ -z "$alias_id" ]; then
  vault write identity/entity-alias name="$name" canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid"
fi
```

Prepare the registration with its ceiling policy:

```bash
jq -n --arg name "$name" --arg entity "$entity" --arg policy "$policy" --argjson optional "$optional" '{display_name:$name,entity_id:$entity,ceiling_policies:([$policy]+(if $name=="chatbot-oidc" then ["lumen-block-database-read","lumen-block-database-write","lumen-block-decrypt"] else [] end)),no_default_ceiling_policy:true,optional_authorization_details:$optional,description:"Lumen chatbot laboratory"}' > "$MANUAL/agent-registration.json"
```

Register the agent:

```bash
vault write agent-registry/register - < "$MANUAL/agent-registration.json"
```

Check its registration:

```bash
vault read "agent-registry/registration/display-name/$name"
```

Repeat the configuration steps for `suffix=research` before moving on to section 4.

The OBO actor requires RAR and has an explicit ceiling. The `optional_authorization_details=true` exception is limited to the Tavily agent: its autonomous access is bounded by its entity policy. The xAI, OpenAI and Claude agents require RAR.

## 4. Create the session configuration

Run this line from the repository root, in zsh or Bash. It loads its own environment, queries Vault and creates `chatbot/runtime` only if it is missing. If it exists, it keeps `session_secret` and the current configuration:

```bash
bash scripts/manual/guided-run.sh bash chatbot/scripts/configure-runtime.sh
```

## 5. Synchronize Verify groups to Vault and grant access to the app

Run only the following line from the repository root. The script loads `.env` and the private Vault connection, sets the `verify` namespace and obtains a new administrative token. It does not depend on `MANUAL`, `TENANT` or `VAULT_ADDR` defined in your terminal. If you are still at a `>` prompt from an earlier paste, press **Ctrl+C** before running the line.

First it queries the three groups, their users and the required policies. If a group is missing, it stops before modifying identities or permissions. Then it synchronizes entities/aliases by **user ID** and Vault **internal** groups, and grants those groups access to the OIDC application.

```bash
bash scripts/manual/paso-a-paso.sh ejecutar grupos
```

You can check the requirements without applying changes with `bash scripts/manual/guided-run.sh bash chatbot/scripts/05-sync-groups.sh --check`.

After membership changes, repeat the synchronization, restart Lumen to load the IDs/names and obtain a new OIDC session. The JWT already issued keeps its claims, but Vault membership and policies are evaluated with the server's state.

<a id="6-política-bootstrap-y-comprobaciones"></a>
## 6. Bootstrap policy and checks

Each line loads its own environment. The policy is applied from [bootstrap.hcl](../../chatbot/policies/bootstrap.hcl), the same file the deployment uses.

```bash
bash scripts/manual/guided-run.sh bash scripts/manual/iam.sh bootstrap
```

The app does not use root. This bootstrap reads the OAuth credentials of the three model agents and their configuration; it does not read `verify-admin`, Tavily, xAI keys, SQL data or protected data. It revokes itself after loading them.

```bash
bash scripts/manual/guided-run.sh bash scripts/manual/iam.sh check
```

Local sources: [04-vault-agents.sh](../../chatbot/scripts/04-vault-agents.sh), [05-sync-groups.sh](../../chatbot/scripts/05-sync-groups.sh). The test with a delegated JWT is in [11](11-obo.md).
