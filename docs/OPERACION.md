# Operating Lumen

This guide covers administrative access, maintenance and teardown. To install and
try the demo, start with the [main README](../README.md). Run the
commands from the repository root.

<a id="acceso-a-vault-y-grafana"></a>
## Access to Vault and Grafana

Access credentials are generated during `./demo.sh start`. The following commands use the default state directory; if you set `LUMEN_STATE_DIR`, replace `~/.local/state/lumen-vault-demo` with that path.

### Vault

1. Open https://127.0.0.1:8443/ui/.
2. Select the **Token** method and leave the namespace empty.
3. Copy the lab root token to the clipboard:

```bash
jq -jr '.root_token' \
  ~/.local/state/lumen-vault-demo/vault/cluster-keys.json | pbcopy
```

Paste it to sign in. Inside Vault, select the **`verify`** namespace to see the integrations.

### Grafana

Open http://localhost:3000 and sign in with the **`lumen-admin`** user. Retrieve its password from Vault and copy it to the clipboard:

```bash
(
  source ~/.local/state/lumen-vault-demo/vault/config.env
  export VAULT_ADDR VAULT_TOKEN VAULT_CACERT

  vault kv get \
    -namespace=verify \
    -mount=secrets \
    -field=password \
    chatbot/observability | pbcopy
)
```

Paste the password and open the [Lumen dashboard](http://localhost:3000/d/lumen-iam). The commands copy the credentials without showing them in the terminal; run each one right before you paste its value.

<a id="qué-configura-el-arranque"></a>
## What startup configures

1. Checks tools, `.env`, the container engine and Verify discovery.
2. Starts/creates the **workshop** Minikube profile and deploys/adopts Vault Enterprise with TLS and three Raft nodes; it initializes only an empty cluster and unseals the nodes.
3. Deploys/adopts MySQL Enterprise with `keyring_okv` and KMIP; existing data and certificates are kept.
4. Prepares the **verify** Vault namespace, KV v2 and the static entries.
5. Configures RAR, the OAuth profile, OIDC/STS applications, users, groups, entities, policies and registered agents.
6. Creates the MySQL RO/RW roles, catalog, sample inventory, Transit, tokenization and the applications table. Prepares the task agents, personal spaces and CIBA; contracting requires its initial verification and enablement.
7. Configures the three providers: dynamic xAI with a 5 min TTL / 10 min maximum, OpenAI with a Vault JWT-SVID and discovery/JWKS through ngrok, and Claude with its own SPIFFE identity and federation. The external OpenAI resources from the initial setup are kept.
8. Enables auditing, applies Grafana/Loki/Tempo/Alloy, opens local ports and starts Lumen.
9. Checks SPIFFE federation and a real Claude inference, and runs application, SQL permission, agent limit and real Tavily search tests. A failure returns a non-zero exit code and identifies the failed stage.

It can be repeated: it reuses resources by name, does not delete profiles/PVCs, and does not reinitialize Vault or regenerate secrets for existing clients. It updates managed configuration and restarts Lumen to load it; chatbot sessions are lost during that restart. It reconciles the three-plan catalog and keeps saved applications.

Fixed context: `workshop`; Kubernetes namespaces: `vault`, `mysql`, `lumen-observability`; Vault namespace: `verify`. These names are fixed in the manifests. A new installation omits the injector/CSI because Lumen does not use them.

### Vault initialization and generated credentials

The bootstrap order is:

1. Read the external entries from `.env`, without needing a Vault token.
2. Deploy Vault and, only if it is not initialized, run `vault operator init`.
3. Store the root token and unseal keys in `~/.local/state/lumen-vault-demo/vault/cluster-keys.json`, with `600` permissions.
4. Unseal Vault and generate `vault/config.env` inside that state directory, with the TLS connection and the provisioning token.
5. Configure the integrations using that file. The application then receives a limited bootstrap token, not the root token.

## Updating the application

With the infrastructure running, to publish the local code and restart Lumen:

```bash
bash scripts/demo/start.sh
```

`chatbot/app/` and `chatbot/static/` are copied to the managed runtime and the
observability tunnels are renewed. The restart ends sessions and loses conversations,
unsaved forms and in-memory captures. Saved applications and
confirmed contracts persist in the services.

To also reconcile infrastructure, policies and integrations, use
`./demo.sh start`. For a manual run, follow
[Updating an existing installation](manual/10-aplicacion.md#actualizar-una-instalación-existente).

To change the preconfigured models, adjust the `LUMEN_*_MODEL` variables
in `.env`, run `bash chatbot/scripts/configure-models.sh` and restart Lumen.
`configure-models.sh` republishes the full catalog and sets the initial provider
to the one in `LUMEN_MODEL_PROVIDER`.
Choosing another provider from the banner only affects that session and keeps its
conversation; the process does not need to be restarted.

<a id="sincronizar-las-claves-de-claude"></a>
## Syncing the Claude keys

`LUMEN_CLAUDE_SYNC_MODE=api` uses the local `ant` administrative profile to
update only the public keys of the existing issuer and check that they persist.
`console` exports the public array, which must then be saved to the issuer from the
console. Both modes keep the subsequent federation and inference check.
[Setup and limits](manual/08-claude-spiffe.md).

To sync or export the current keys without reinstalling:

```bash
bash scripts/demo/claude-issuer.sh
```

The array is written to `claude/issuer-keys.json` and the result to
`claude/issuer-sync.json`, inside the state directory. In `console` mode, the
exporter report stays pending: exporting does not prove that the console has
saved the keys. After saving them, check the federation:

```bash
./demo.sh verify --provider anthropic
```

Rotating keys while the demo is running also requires syncing the keys
online. There is no periodic synchronizer for Claude.

<a id="retirar-y-reconstruir"></a>
## Teardown and rebuild

First review the inventory and the IDs that would be deleted:

```bash
./demo.sh remove --dry-run
```

To run that teardown:

```bash
./demo.sh remove
```

**`remove` deletes data irreversibly**: the Kubernetes namespaces `vault`, `mysql` and `lumen-observability`, all their contents and their PVCs. This includes every secret and internal namespace in that Vault (including historical exercises stored there), the MySQL applications and the Loki/Tempo logs/traces. It uninstalls the `vault` Helm release, including its cluster-scoped resources. The `workshop` Minikube profile and other namespaces remain available.

In Verify it deletes only these names, resolving and checking their IDs through the API:

| Type | Deleted resources |
|---|---|
| Applications | `vault-chatbot-oidc`, `vault-chatbot-research`, `vault-chatbot-xai`, `vault-chatbot-openai`, `vault-chatbot-anthropic`, `vault-chatbot-task-read`, `vault-chatbot-task-write`, `vault-chatbot-task-reveal`, `vault-chatbot-contract` and the earlier experiment `vault-chatbot-pdf-approval` |
| STS client | `vault-chatbot-sts` |
| Fictitious users | `lumen-reader`, `lumen-writer`, `lumen-supervisor` and `lumen-validator`, if it exists |
| Groups | `chatbot-readers`, `chatbot-writers`, `chatbot-supervisors` and the `chatbot-validators` group marked as owned by Lumen |

It keeps `.env`, the administrative API client, the shared `vault:path_access` schema, `vault-authn-entry`, `vault-obo-sts` and the other Verify accounts/applications. It does not change Okta. User/group deletions use `notifyType=NONE`, with no notification emails. It checks that the accounts are the fictitious Cloud Directory accounts and that the groups contain no members outside the demo; it stops if it finds duplicates or incomplete inventories.

The `chatbot-validators` group is identified by `externalId=lumen-demo:contract-validators`; the group is deleted, but the real account selected as Validator is kept. Verify may omit the OAuth identifier of the disabled PDF experiment: that exception is only accepted for its exact name, description and template, with the application and sign-in disabled.

It first stops Lumen and synchronously revokes the leases under `verify/xai/creds/lumen/`. It then deletes the Verify resources, stops the managed tunnels, removes MySQL/observability and finally Vault. If Verify, the revocation or the volume removal fails, it returns an error and keeps the recovery keys. It does not use `revoke-force` or remove finalizers to hide failures. If there are PVs with a `Retain` policy, they must be resolved before data is removed.

After confirming the remote deletion, it deletes `vault/`, `mysql/`, `runtime/`, `vault-chatbot-storage/`, `services/`, `pids/`, `ngrok/` and `openai/` from the state directory. It removes the compatible key/connection copies in `/tmp/vault` only if they match this deployment, plus the local file `/tmp/lumen-telemetry/spans.jsonl`. It keeps sources, screenshots, historical reports, launcher logs and image/dependency caches. Therefore, "clean" means new operational resources; earlier reports remain historical evidence.

`remove` requires access to the `workshop` profile; if it is stopped, start it with `minikube start -p workshop`. If Vault exists and is already initialized, it must be unsealed and have its private bootstrap available to revoke the external keys. Verify administrative authentication comes directly from `.env`, so it does not depend on the secrets about to be deleted. `remove` can be repeated after a partial run or when the resources have already been removed.

The inventory is saved to `~/.local/state/lumen-vault-demo/remove-plan.json`; a completed teardown generates `last-remove.json`. `start` and `remove` share the launcher lock so they never run at the same time. The next `start` creates a new CA, unseal keys/root token, data and OAuth clients; the initial external passwords are kept in `.env`.

With the external entries and federations in place, rebuild with:

```bash
./demo.sh start
```

If Claude uses `console`, update the new JWKS in the issuer before its verification
can pass. CIBA again requires its real test and enablement when
the client is recreated. Follow [CIBA contracting](manual/17-contratacion-ciba.md).

## Private state and processes

State, logs and reports are stored in `~/.local/state/lumen-vault-demo/`, configurable
with `LUMEN_STATE_DIR`. The Vault bootstrap is kept there and a
compatible copy is kept in `/tmp/vault/config.env`. Keys from another cluster cause
an explicit stop; they are not overwritten.

If `/tmp/vault` belongs to another lab, set `LUMEN_LEGACY_VAULT_COMPAT=0`
for both `remove` and `start`. This disables legacy key adoption, connection-file
copies and legacy cleanup; all Lumen state stays in `LUMEN_STATE_DIR`.
For example, run `LUMEN_LEGACY_VAULT_COMPAT=0 ./demo.sh remove --dry-run`
before the corresponding removal and start commands. Existing default ownership
checks remain enabled when the option is absent. Ports still must be free or
owned by this demo.

Lumen and the port-forwards use `launchd` user services with private
definitions in `services/`. They stay active after the command ends; the tunnels
recover if they end after a pod restarts. They are not configured to start
automatically at macOS login. `stop` stops those local processes
and keeps the cluster and its data.

`start` replaces the tunnels for the expected context, namespace and target; it rejects
ports held by unrelated processes. It only restarts Lumen if the process belongs
to the workspace or to its managed runtime. The code is copied to `runtime/chatbot`
outside Google Drive so that `launchd` can run it.

The lab raw capture can include JWTs, Vault responses and messages
to the model. `LUMEN_VAULT_AUDIT_MODE`, `LUMEN_TRACE_VAULT_RAW` and `LUMEN_TRACE_CONTENT`
are controlled in `.env`. [Content, access and retention](../chatbot/OBSERVABILITY.md).

## Adopting an existing lab

This section only applies if you already have deployed resources. The from-scratch installation flow uses the external credentials entered directly in `.env`.

If Vault is already initialized, its saved keys are required: the launcher reuses the private state or migrates `/tmp/vault/cluster-keys.json` from the previous lab. It cannot regenerate the keys of an existing cluster or reinitialize it to recover them.

`bash scripts/import-env.sh` is an **optional migration from an already running lab**: it collects the Vault entries, `oracle.env` and `vault.hclic` without displaying them. It does not run when starting from scratch and does not import the root token; in a new installation the external credentials are filled in directly in `.env`. It does not overwrite a `.env` that already contains the integration.

## VM clock

After macOS sleeps, check that the Podman VM keeps the correct time. `start` detects drifts of more than 60 seconds before issuing certificates or initializing Vault; a drift can also invalidate JWTs. If you use Podman and its VM is behind the host, look up its name with `podman machine list`. For example, for `podman-machine-default`:

```bash
podman machine ssh podman-machine-default sudo -n date -u -s "@$(date -u +%s)" </dev/null
./demo.sh start
```

The command syncs the VM clock with the host clock. It does not disable TLS validation or reinitialize Vault. During a long demo you can run `caffeinate -i -m` in another terminal to prevent automatic sleep.

The Vault OAuth profile and the client apply a **15-second leeway** when validating JWT dates. This avoids rejecting freshly issued tokens because of small differences between Verify and the VM; it does not fix a clock that is several minutes behind. [Official `clock_skew_leeway` parameter](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server).
