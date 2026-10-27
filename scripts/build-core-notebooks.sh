#!/usr/bin/env bash
# Notebooks are explanations/wrappers; deployment code has a single source.
set -euo pipefail
cd "$(dirname "$0")/.."
work=$(mktemp -d /tmp/lumen-core-notebooks.XXXXXX)
trap 'rm -rf "$work"' EXIT
new() { printf '[]' > "$work/cells.json"; }
cell() {
  cat > "$work/source"
  jq --arg kind "$1" --rawfile text "$work/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($text|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$work/cells.json" > "$work/next.json"
  mv "$work/next.json" "$work/cells.json"
}
save() {
  jq '{cells:.,metadata:{kernelspec:{display_name:"Python 3 (IPython + Bash)",language:"python",name:"python3"},language_info:{name:"python"}},nbformat:4,nbformat_minor:5}' "$work/cells.json" > "$1"
}
new
cell markdown <<'MD'
# Vault Enterprise on Minikube

The complete demo is started from the repository root with **`./demo.sh`**. This notebook documents only the Vault stage and uses the same scripts, without deleting Minikube profiles or reinitializing an existing cluster.

[Installation and input secrets](README.md) · [Workspace review](docs/WORKSPACE_REVIEW.md).

Prepare `.env` from `.env.example`: license, external integration credentials and image configuration. Do not add `VAULT_TOKEN`, `VAULT_ADDR` or `VAULT_CACERT`: the launcher generates the bootstrap after initializing Vault. The generated state (CA, initialization keys, administrative token, logs and PID) is stored in `~/.local/state/lumen-vault-demo`, outside `/tmp` and the workspace. `LUMEN_STATE_DIR` allows a different location. Adopting an already initialized Vault requires its saved keys; they are not regenerated.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh check
CODE
cell markdown <<'MD'
## Rerunnable deployment

Creates or starts the `workshop` profile; existing resources are preserved. On an empty installation it pulls the `josemerchan/vault-xai:2.2.0-ent` image, which bundles the xAI plugin (AMD64/ARM64), from Docker Hub, deploys three Raft nodes with TLS, initializes once and unseals the nodes. `.env` lets you set `VAULT_IMAGE_REPOSITORY` and `VAULT_IMAGE_TAG`. Port 8443 listens on `127.0.0.1`.

If Vault already exists, it checks the image and adopts the keys from the previous lab; it does not replace the image or regenerate certificates. The plugin catalog is global, but the xAI engine used by Lumen is configured in `verify`.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/vault.sh
CODE
cell code <<'CODE'
%%bash
source scripts/demo/common.sh
load_inputs
load_vault
vault status
kubectl --context workshop -n vault get pods
helm --kube-context workshop -n vault list
CODE
cell markdown <<'MD'
## `verify` namespace, integration secrets and OAuth profile

The following notebooks work in the `verify` namespace. This cell creates it if missing, imports the `.env` inputs into `verify/secrets` without displaying them, registers the RAR type `vault:path_access` in Verify and configures the Vault OAuth profile. It can be rerun and preserves user passwords that are already stored.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/bootstrap.sh
bash verify/scripts/configure-base.sh
CODE
cell markdown <<'MD'
To resume, use `./demo.sh start`; do not run `minikube delete --all`, delete keys manually or run `operator init` again. `./demo.sh stop` stops only local processes and keeps the cluster and data. To tear down the whole lab, review `./demo.sh remove --dry-run` and run `./demo.sh remove`: it deletes the three namespaces/PVCs and the Lumen resources in Verify, keeps `.env` and allows a new `start`. [Scope of the removal](README.md#volver-a-empezar-desde-cero). Single-share initialization is a lab simplification.
MD
save 1_Deploy_Vault_minikube.ipynb

new
cell markdown <<'MD'
# MySQL Enterprise with KMIP

`./demo.sh` includes this stage. It reuses `mysql/mysql-enterprise-0`; an empty installation uses MySQL Enterprise 8.3.0, with the `aarch64` variant on ARM64. The Oracle registry credentials and the initial password are in `.env`. Registry access must be enabled beforehand in the Oracle account.

Vault serves KMIP at `vault-kmip.vault.svc.cluster.local:5696`. MySQL loads `keyring_okv`; the Lumen tables use `ENCRYPTION='Y'`. Existing client certificates are preserved.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/mysql.sh
CODE
cell markdown <<'MD'
## Check the plugin and encryption

The query uses the password from the pod environment and does not display it. The tables appear after running the database roles stage.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
kubectl --context workshop -n mysql exec -i mysql-enterprise-0 -c mysql -- \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch' <<'SQL'
SELECT PLUGIN_NAME, PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME='keyring_okv';
SELECT NAME, ENCRYPTION FROM INFORMATION_SCHEMA.INNODB_TABLESPACES WHERE NAME LIKE 'scripting/%';
SQL
CODE
cell markdown <<'MD'
The automated demo does not change the KMIP port to simulate failures, does not rotate the InnoDB master key and does not reinstall UDF functions. Those were manual exercises from the previous lab; they are not Lumen requirements. Nor does it restart MySQL on every run or delete its PVCs.
MD
save 2_vault-demo-kmip-mysql.ipynb

new
cell markdown <<'MD'
# Database Secrets Engine: Lumen RO/RW

`./demo.sh` includes creating the catalog, tables and roles. It reuses MySQL/KMIP from [notebook 2](2_vault-demo-kmip-mysql.ipynb). The application's connection and roles live in the Vault namespace **verify**, not in the root namespace.

| Role | SQL privileges | TTL / max |
|---|---|---|
| `chatbot-readonly` | SELECT on `scripting.*` | 120 s / 300 s |
| `chatbot-readwrite` | SELECT, INSERT, UPDATE, DELETE on `scripting.*` | 120 s / 300 s |

Vault manages the `vault_chatbot_admin` account and rotates its password when creating the connection. The application requests credentials with OBO and RAR; the human profile, the agent ceiling and the RAR must all allow the path.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/01-database.sh
CODE
cell code <<'CODE'
%%bash
source verify/scripts/common.sh
for role in chatbot-readonly chatbot-readwrite; do
  vault read -format=json "database/roles/$role" | jq --arg role "$role" '{role:$role,db_name:.data.db_name,default_ttl:.data.default_ttl,max_ttl:.data.max_ttl,creation_statements:.data.creation_statements}'
done
CODE
cell markdown <<'MD'
## Verification

After the full deployment, the check validates SELECT, allows INSERT with RW, denies INSERT with RO and rolls back. It also checks Tavily and the bootstrap token limits. Per-user OBO tests require that user's real login in Verify.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/test-infrastructure.sh
CODE
cell markdown <<'MD'
The old `database/config/mysql` connections and the `payments-app` static role in the root namespace belong to another exercise; if they exist they are preserved, but Lumen does not use them. The `5_Payments_App.ipynb` application is not included; it is not part of this workspace.

[Notebook 8](8_Lumen_Protected_Applications.ipynb) adds Transit/Transform. The supervisor uses SQL RO and separate permissions to reveal data; the writer uses SQL RW and can protect data, but not reveal it.
MD
save 3_Database_Secret_Engine.ipynb

new
cell markdown <<'MD'
# xAI: dynamic credentials from Vault

`./demo.sh` includes these stages. The plugin is bundled in the `josemerchan/vault-xai:2.2.0-ent` image published on Docker Hub; it requires neither a build nor a local copy of its repository. The management key comes in through `XAI_MANAGEMENT_API_KEY`, is kept in `verify/secrets/xai_mgmt` and configures `verify/xai`.

The application uses the **Client Credentials** of `chatbot-xai` to read `xai/creds/lumen?ttl=300`. It does not read `secrets/xai`. On an empty installation the role has a 5 min TTL, a 10 min maximum and native expiry; on an existing one the user-configured role is preserved and checked to allow the requested TTL.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/xai.sh
CODE
cell markdown <<'MD'
## Configuration without displaying keys
MD
cell code <<'CODE'
%%bash
source verify/scripts/common.sh
vault read -format=json xai/config | jq '.data|{api_endpoint,team_id}'
vault read -format=json xai/roles/lumen | jq '.data|{acls,ttl,max_ttl,set_native_expiry}'
CODE
cell markdown <<'MD'
## Identity of the `chatbot-xai` agent

Requires the Verify applications and users from [notebook 6](6_Lumen_Chatbot_Vault_IAM.ipynb) (`02-verify-apps.sh`): the `vault-chatbot-xai` application is created from the `chatbot/research` template. It registers the agent with mandatory RAR and selects xAI as the model provider.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/configure-xai.sh
CODE
cell markdown <<'MD'
## Test inference and real expiry

The test issues a disposable 60 s key, calls Grok, checks denials and waits for it to expire. It revokes only its own lease. It does not print the key, does not revoke by prefix and does not affect the keys Lumen is using.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/verify-xai.sh
CODE
cell markdown <<'MD'
The current plugin does not implement renewal. Lumen reuses a key while it covers the execution budget and requests another when 210 s or less remain. Vault revokes the previous one when it expires and xAI applies its native expiry. See [lifecycle and traces](chatbot/README.md#xai-con-claves-dinámicas).
MD
save 4_XAI_Secret_Engine.ipynb
