# Lumen · Vault Agentic IAM

Lumen is an authorization demo for AI agents. It uses an energy assistant as an
example: users browse plans, save applications containing protected data, and
request approval for a fictional contract.

**IBM Verify authenticates the user, and Vault decides which operations the agent
can perform on their behalf.** The demo exposes those decisions through real
calls to Vault, MySQL, and model providers. All data and contracts in the walkthrough
are for testing; no action signs up for an energy supply service.

[Install](#installation) · [Try the demo](#try-the-demo) ·
[Verify](#verification) · [Operate or remove](#operations) ·
[Step-by-step manual](docs/manual/README.md)

![Current Lumen interface](docs/screenshots/current/home.jpg)

<a id="qué-demuestra"></a>

## What it demonstrates

| Workflow | What it verifies |
|---|---|
| Read, save, or reveal an application | Vault combines user permissions, agent limits, and the request's RAR restrictions. MySQL credentials are temporary. |
| Protect personal data | Transit encrypts data, and Transform tokenizes national ID numbers (DNI) and IBANs. Authorized profiles can retrieve them. |
| Switch models | OpenAI and Claude use SPIFFE identities issued by Vault; xAI receives dynamic keys. Users can switch providers without losing the conversation. |
| Create a contract with approval | A Validator confirms the request in Verify through CIBA. The contract is then recorded in MySQL, and its owner can download the PDF. |
| Inspect an operation | Lumen traces and Grafana/Tempo/Loki show the exchanges and authorization results. |

The application is built with NiceGUI and LangChain Deep Agents. MySQL Enterprise
uses KMIP for its encryption keys. Web search uses Tavily. The interface supports
English and Spanish.

<a id="prerrequisitos"></a>

## Prerequisites

The launcher in this repository targets **macOS** and uses `launchd`.
Podman or Docker must be running, with capacity for a Minikube VM with
**4 CPUs and 8 GiB of memory**. The demo's Kubernetes context is `workshop`.

Install Bash, Python 3, curl, jq, OpenSSL, Vault CLI, kubectl, **Helm 4**, Minikube,
uv, ngrok, rsync, lsof, and ripgrep (only `remove` uses ripgrep). `plutil` and `launchctl`
are included with macOS.
Node.js is only required to run the local JavaScript tests. The `ant` CLI is used
if you choose to synchronize Claude through its administrative API.

| External service | What you need to prepare |
|---|---|
| IBM Verify | A tenant and an administrative API client with the permissions listed in [00 · Environment](docs/manual/00-entorno.md#cliente-api-administrativo-en-ibm-verify). |
| Vault Enterprise | A license covering Agentic IAM, KMIP, and Transform. |
| Oracle Container Registry | An account with access to the MySQL Enterprise image. |
| OpenAI | An organization with API access, quota, and an administrative key to set up the project, service account, and federation. |
| xAI | A Management API key with access to the demo's team. |
| Claude | An organization with API access, quota, and permission to set up service account federation. |
| Tavily | An API key for web search. |
| ngrok | An account and a domain you control to publish SPIFFE discovery and public keys. |

**A full startup configures all three providers.** Selecting one with `--provider`
changes the initial selection but does not remove the requirements for the other
two. The launcher creates the local infrastructure and Lumen resources in Verify;
external accounts and their permissions must be prepared beforehand.

<a id="instalación"></a>

## Installation

Run commands from the repository root. To proceed one operation at a time, use
the [guided installer](docs/manual/PASO-A-PASO.md). To perform each operation with
individual commands, follow the [manual](docs/manual/README.md).

<a id="preparar-env"></a>

### Prepare `.env`

The configuration lives next to the private local state, outside the workspace,
because the workspace may be a synced folder. Create it without overwriting an
existing file:

```bash
state="${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}"
mkdir -p "$state" && chmod 700 "$state"
cp -n .env.example "$state/.env" && chmod 600 "$state/.env"
```

Set `DEMO_ENV_FILE` to use another path. A `.env` left in the workspace root still
works, but every command prints how to move it.

Open that `.env` in your editor and complete the entries in [`.env.example`](.env.example):

- Verify tenant and administrative credentials.
- xAI, OpenAI, Tavily, and Oracle credentials, and the Vault license.
- Initial passwords for MySQL and for `lumen-reader`, `lumen-writer`, and `lumen-supervisor`.
- Your `NGROK_DOMAIN`; add `NGROK_AUTHTOKEN` if ngrok is not authenticated locally.
- Container engine. For Docker, change **both** `CONTAINER_ENGINE` and
  `MINIKUBE_DRIVER` to `docker`.

The OpenAI/Claude federation IDs are filled in during the next step. `.env` uses
Bash syntax and never enters the workspace or Git. Do not add `VAULT_TOKEN`, `VAULT_ADDR`, or
`VAULT_CACERT`: the installer generates the Vault bootstrap configuration and
stores it in the private state directory.

<a id="preparar-openai-y-claude-por-primera-vez"></a>

### Set up OpenAI and Claude for the first time

If you already have the demo's federations and their IDs in `.env`, keep those
resources and proceed to the prerequisite check.

**1. Prepare the Vault issuer and OpenAI resources:**

```bash
./demo.sh prepare-openai
```

This command **deploys and initializes Vault** if needed. It publishes only
discovery/JWKS through ngrok and creates or reuses the OpenAI project and service
account. Then complete the [WIF provider and its mapping](docs/OPENAI_SPIFFE.md#preparación-inicial-de-openai)
in the OpenAI console and save `OPENAI_IDENTITY_PROVIDER_ID` in `.env`.

**2. Register the Claude federation.** Reuse the public keys from the issuer you
just prepared. With the default state directory, copy them as follows:

```bash
(
  source "${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}/vault/config.env"
  export VAULT_ADDR VAULT_TOKEN VAULT_CACERT
  vault read -namespace=verify -format=json spiffe/.well-known/keys |
    jq -c '.data.keys' | pbcopy
)
```

Follow the [Claude issuer and rule setup](docs/manual/08-claude-spiffe.md#3-registrar-la-federación-usando-el-portal-claude).
The issuer URL is `https://<your-NGROK_DOMAIN>/v1/verify/spiffe`; the rule uses the
subject and audience specified in that guide. Save the template's five
`ANTHROPIC_*` IDs in `.env`. Startup will create the Vault role for Claude.

**3. Choose how to keep Claude's public keys up to date:**

| `LUMEN_CLAUDE_SYNC_MODE` | Setup and behavior |
|---|---|
| `api` — template default | Install `ant` and sign in with the administrative profile specified in the [Claude guide](docs/manual/08-claude-spiffe.md). The installer updates and checks the existing issuer's keys. |
| `console` | Update the inline keys in the Claude console. The installer exports `claude/issuer-keys.json` inside the state directory but does not save them in Claude. |

With `console`, you must save the new keys in the issuer after recreating Vault.
If `start` stops at the Claude check, update the keys and rerun the command.
Both modes require successful live federation and inference checks.
[Synchronization and rotation](docs/OPERACION.md#sincronizar-las-claves-de-claude).

<a id="comprobar-e-instalar"></a>

### Check and install

Once the inputs and federations are ready:

```bash
./demo.sh check
```

This checks tools, variables, the container engine, and Verify discovery.
In Claude `api` mode, it also checks administrative access to the issuer and its
rule. It does not deploy services or, on its own, validate every integration.

```bash
./demo.sh start
```

This command prepares Vault, MySQL, identities and policies, all three providers,
audit logging, observability, and the application. It runs application and
infrastructure tests and a federated inference request with Claude. If it fails,
it identifies the stage and the corresponding private log.

The command can be repeated: it reuses existing resources and updates their
configuration. It preserves saved applications but restarts Lumen and ends its
sessions. [Startup details](docs/OPERACION.md#qué-configura-el-arranque).

<a id="probar-la-demo"></a>

## Try the demo

Open **[http://localhost:8088](http://localhost:8088)**, click **Sign in with Verify**,
and choose **Cloud Directory**. Use `localhost`, because the OIDC callback is
configured with that hostname. The initial passwords are the ones you chose in `.env`.

| User | Main workflow |
|---|---|
| `lumen-reader` | Browse the catalog and view masked applications. |
| `lumen-writer` | Browse and save applications containing protected data. |
| `lumen-supervisor` | Read and reveal data through Vault; cannot save applications. |

1. Sign in as Reader, ask for the plans, and click **Check limits in Vault**.
2. Sign in as Writer and create an application using **Use test data**.
3. Sign in as Supervisor, open the application, and reveal its data.
4. Open each operation's trace to inspect the identity, calls, and permissions
   applied. [Walkthrough and observability](chatbot/OBSERVABILITY.md).

The OpenAI/xAI/Claude selector changes the model for the next request while
preserving the conversation. **EN / ES** changes the language. These controls do
not change the user's permissions.

Additional workflows have their own guides:

- [Task agents](docs/manual/14-agentes-por-tarea.md): compare different limits with the same user.
- [RAR parameters](docs/manual/15-parametros-rar.md): restrict request parameters.
- [Personal spaces](docs/manual/16-espacios-personales.md): verify KV isolation between users.
- [CIBA contracting](docs/manual/17-contratacion-ciba.md): prepare a Validator, approve a request, and download the PDF. **A fresh installation leaves this feature disabled until its live test has passed and it is explicitly enabled.**

<a id="acceso-a-vault-y-grafana"></a>

### Access Vault and Grafana

- [Vault](https://127.0.0.1:8443/ui/): integrations are in the `verify` namespace.
- [Grafana](http://localhost:3000/d/lumen-iam): traces and audit dashboard.

Instructions for retrieving their credentials are in
[Access to Vault and Grafana](docs/OPERACION.md#acceso-a-vault-y-grafana).

<a id="verificación"></a>

## Verification

To check pods, deployments, and local endpoints:

```bash
./demo.sh status
```

To run application and infrastructure tests and check federation and inference
for the selected provider:

```bash
./demo.sh verify --provider openai
```

You can also use `--provider xai` or `--provider anthropic`. These checks require
running services and incur actual provider usage. Human login, authorization
matrices, CIBA, and visual review have additional tests described in their
chapters; `verify` does not run all of them.

The latest launcher result is stored in `~/.local/state/lumen-vault-demo/last-run.json`;
`start`, `verify`, `prepare-openai`, `block`, `unblock`, and `remove` also keep a copy per
run in `reports/` inside that directory. The [October 22, 2026 run](docs/runs/20261022T122934Z-full-e2e/README.md)
documents the reinstallation, results, and browser download step that remained
unconfirmed. The [validation history](docs/manual/VALIDACION.md) preserves other
runs with their dates and scope.

The [October 27 manual and script validation](docs/runs/20261027T091528Z-manual-and-script/README.md)
records two independent rebuilds, current test results, browser checks and the
fixes required after the English UI and OpenAI model changes.

<a id="operación"></a>

## Operations

| Command | Effect |
|---|---|
| `./demo.sh start` | Prepare or reconcile the demo and start local processes. |
| `./demo.sh stop` | Stop managed local processes; preserve the cluster and its data. |
| `bash scripts/demo/start.sh` | Deploy the application code and restart it with the infrastructure already running. |
| `./demo.sh blocks` | Inspect access blocks. |
| `./demo.sh block database-write` | Block new writes and revoke affected SQL leases. |
| `./demo.sh unblock database-write` | Remove that block. |

The block targets are `xai`, `database-read`, `database-write`, and `decrypt`.
[Behavior and scope](docs/ACCESS_BLOCKS.md). For logs, keys, rotation, upgrades,
and clock issues, see the [operations guide](docs/OPERACION.md).

<a id="volver-a-empezar-desde-cero"></a>

### Start over from scratch

First, review the inventory:

```bash
./demo.sh remove --dry-run
```

To perform the removal:

```bash
./demo.sh remove
```

**This permanently deletes Vault, MySQL, and observability data**, their Kubernetes
namespaces and volumes, and the inventoried Lumen resources in Verify. It preserves
the code, `.env`, Minikube, external OpenAI/Claude federations, and the real Validator
account. Read the [full scope](docs/OPERACION.md#retirar-y-reconstruir) before running
it. Afterwards, `./demo.sh start` recreates the demo; if you use Claude in `console`
mode, you must update its public keys.

<a id="revisión-y-pruebas-locales"></a>

## Local review and tests

These checks use mocked services and do not require deploying the demo.
If the Python environment is missing, create it with `bash chatbot/scripts/install.sh`.

```bash
/tmp/vault-chatbot-venv/bin/python -m pytest -q
```

```bash
node --test chatbot/tests/*.test.mjs
```

```bash
python3 scripts/manual/validate.py
```

The last command validates syntax, local links and anchors, notebook Markdown,
and the provenance of guide screenshots.
Reference notebooks must remain free of saved outputs and execution counts.

<a id="documentación-del-repositorio"></a>

## Repository documentation

| Document | Purpose |
|---|---|
| [Configuration manual](docs/manual/README.md) | Understand and execute each stage with individual commands. |
| [Guided installer](docs/manual/PASO-A-PASO.md) | Run scripts one operation at a time and resume after an error. |
| [Application](chatbot/README.md) | Architecture, profiles, providers, and code maintenance. |
| [Observability](chatbot/OBSERVABILITY.md) | Inspect calls, captured data, and audit events; includes the console for live requests. |
| [Operations](docs/OPERACION.md) | Administrative access, upgrades, private state, and removal. |
| [Final repository validation · October 22](docs/runs/20261022T161825Z-repo-validation/README.md) | Final code, tests, notebooks, links, screenshots, and runtime. |
| [Comprehensive review · October 22](docs/runs/20261022T140230Z-workspace-review/README.md) | Current interface, screenshots, services, and verification limits. |
| [How Vault decides · October 22](docs/runs/20261022T154444Z-vault-decision/README.md) | Authorization details for each Vault call, with correlated audit events and their limits. |
| [Code review](docs/WORKSPACE_REVIEW.md) | Findings, fixes, and regression tests. |

The notebooks at the repository root document demo stages and reuse its scripts;
they are not required by the launcher. [Verify](verify/README.md) and [Okta](okta/README.md)
retain separate exercises. Lumen's active path uses **IBM Verify**; Okta is outside
its installation scope.
