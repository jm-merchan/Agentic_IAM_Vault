# 10 · Start Lumen and check the walkthroughs

[Index](README.md) · Requires 00–05, [xAI](06-xai.md), [OpenAI](07-openai-spiffe.md), [Claude](08-claude-spiffe.md) and [09](09-observabilidad.md)

## 1. Review the configuration the app will load


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
# The profiles are generated in 06 section 6, 07 section 7 and 08 section 6.
# None of those sections changes the published catalog on its own.
initial=${LUMEN_MODEL_PROVIDER:-auto}
case "$initial" in auto) initial=openai;; openai|xai|anthropic) ;; *) echo 'Invalid initial provider' >&2; exit 1;; esac
for provider in openai xai anthropic; do
  test -s "$MANUAL/model-$provider.json"
  vault kv metadata get -mount=secrets "chatbot/$provider" >/dev/null
done
jq -en --arg initial "$initial" \
  --slurpfile openai "$MANUAL/model-openai.json" \
  --slurpfile xai "$MANUAL/model-xai.json" \
  --slurpfile anthropic "$MANUAL/model-anthropic.json" '
  {openai:$openai[0],xai:$xai[0],anthropic:$anthropic[0]} as $profiles |
  if all($profiles|to_entries[];
    .key==.value.provider and (.value.model|type=="string" and length>0) and
    (.value|has("api_key")|not) and
    .value.credential_source==(if .key=="xai" then "vault_dynamic" else "vault_spiffe" end))
  then $profiles[$initial] + {providers:$profiles}
  else error("Invalid provider profile") end' > "$MANUAL/model-catalog.json"
# Published only if all three profiles pass the validation above.
vault kv put -mount=secrets chatbot/model - < "$MANUAL/model-catalog.json"
for name in oidc research sts runtime model openai xai anthropic; do
  vault kv metadata get -mount=secrets "chatbot/$name" >/dev/null
done
vault kv get -format=json -mount=secrets chatbot/model | \
  jq '.data.data|{initial:.provider,providers:(.providers|map_values({model,credential_source}))}'
vault read -format=json sys/config/oauth-resource-server/verify | \
  jq '.data|{issuer_id,use_jwks,user_claim,actor_claim,optional_authorization_details}'
```

Prepare the three identities beforehand. The block above publishes their profiles together in `chatbot/model` through the Vault CLI; it does not create new identities. It is the manual equivalent of `chatbot/scripts/configure-models.sh`, without running the launcher. The banner lets you choose OpenAI, xAI or Claude without restarting, keeps the conversation and remembers the preference. `LUMEN_MODEL_PROVIDER` or `--provider` only set the initial selection; `auto` uses OpenAI.

<a id="2-instalar-el-runtime"></a>

## 2. Install the runtime

```bash
uv venv --python 3.12 /tmp/vault-chatbot-venv
uv pip install --python /tmp/vault-chatbot-venv/bin/python -r chatbot/requirements.lock.txt
```

If that environment already exists, skip `uv venv`. The locked list reproduces the workspace dependencies: NiceGUI, Deep Agents, model connectors, PyJWT, MySQL and OpenTelemetry. No different framework is installed.

<a id="3-crear-bootstrap-y-arrancar-sin-credenciales-administrativas"></a>

## 3. Create the bootstrap token and start without administrative credentials

Check that the Vault, MySQL and observability forwards are running. In a dedicated terminal, reload the environment first and run:

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json \
  -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m \
  -display-name=lumen-bootstrap | jq -er .auth.client_token)
vault policy write chatbot-agent-inspector "$LUMEN_ROOT/chatbot/policies/agent-inspector.hcl"
export CHATBOT_AGENT_INSPECTOR_TOKEN
CHATBOT_AGENT_INSPECTOR_TOKEN=$(vault token create -format=json -policy=chatbot-agent-inspector -no-default-policy -period=1h -display-name=lumen-agent-inspector | jq -er .auth.client_token)
unset VAULT_TOKEN
unset VERIFY_ADMIN_CLIENT_SECRET XAI_MANAGEMENT_API_KEY XAI_TEAM_ID TAVILY_API_KEY
unset OPENAI_ADMIN_API_KEY OPENAI_API_KEY NGROK_AUTHTOKEN
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE
unset ORACLE_REG_EMAIL ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD
unset LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
export LANGSMITH_TRACING=false
export LUMEN_TRACE_CONTENT=1
export LUMEN_TRACE_VAULT_RAW=1
export LUMEN_TRACE_CONTENT_MAX_BYTES=65536
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
export NICEGUI_STORAGE_PATH="$LUMEN_STATE_DIR/vault-chatbot-storage"
mkdir -p "$NICEGUI_STORAGE_PATH"
chmod 700 "$NICEGUI_STORAGE_PATH"
cd "$LUMEN_ROOT/chatbot"
/tmp/vault-chatbot-venv/bin/python -m app.main
```

The app loads its configuration and revokes the bootstrap token in `load_config()`. Business operations use Verify JWTs, OBO or the SPIFFE identity, depending on the resource. The agent details card uses a separate read-only metadata token, renewed by Lumen and revoked on shutdown; [scope and links](14-agentes-por-tarea.md#identificar-al-agente-y-pivotar-a-vault). Do not reload `session.sh` inside the app process after clearing its variables.

This foreground run lasts as long as the terminal stays open; Ctrl+C stops it. The automated launcher uses launchd and copies the runtime outside Google Drive because of macOS restrictions. That supervision is not needed to understand the manual startup.

## 4. Open the interfaces

| Interface | URL / credential |
|---|---|
| Lumen | `http://localhost:8088`, sign in with Verify → Cloud Directory |
| Vault | `https://127.0.0.1:8443/ui/`, root token generated in 01 (`vault/config.env`), namespace `verify` |
| Grafana | `http://localhost:3000/d/lumen-iam`, `lumen-admin`, secret `chatbot/observability` |

To retrieve a human user's password in another terminal, load [the Vault environment](01-vault.md) and copy it to the clipboard:

```bash
ROLE=reader
vault kv get -format=json -mount=secrets "chatbot/users/$ROLE" | jq -jr .data.data.password | pbcopy
```

Use exactly `localhost` for Lumen, not `127.0.0.1`, because the callback is registered with that hostname. Each user change requires signing out of Lumen and choosing another account in Verify; if the previous user's SSO session persists, sign out of Verify or use a private browser profile.

<a id="idioma-y-comprobaciones-bilingües"></a>

### Language and bilingual checks

The instructions in this manual use the Spanish labels. Press **ES** if you want to follow them literally, or use their English equivalents. The chat, form, inbox and trace viewer have **EN / ES** at the top right; the selection is remembered in the `lumen_language` cookie for one year and takes precedence over the browser. Without it, `Accept-Language` is used, including regional variants and priorities. If no supported language is found, English is used; if the header is missing, Spanish. [Details and equivalents](../../chatbot/README.md#idioma-español-e-inglés).

1. **Initial detection:** with a profile that has no `lumen_language` cookie, open Lumen with English as the browser's preferred language and check the header, the Lumen screen before signing in, and that **EN** is active. Repeat with Spanish; **ES** should be selected. A session already configured with the buttons is not valid for testing initial detection.
2. **Manual switch:** press EN and ES, reload and navigate between chat, applications and traces. The choice must persist, including after login. The switch applies to the model's next response; earlier messages keep their language. Wait for an operation to finish before switching.
3. **Real chat:** choose **EN** and send «What can you help me with? Answer in one sentence.» with OpenAI, xAI and Claude, waiting between queries. They must answer in English. Switch back to **ES** and ask «Dame un consejo breve para ahorrar energía en casa» ("Give me a short tip to save energy at home"). Check that the chosen provider and the history are kept.
4. **Catalog and proposal:** use «Find your plan» or ask «Show the energy plans in Lumen's catalogue». Titles and descriptions must appear in English, plan names are kept, and prices come from a current OBO query. As the writer, ask for a proposal for a specific plan: **Continue application** opens the form; the proposal is not saved yet.
5. **Form:** as the writer, go to step 2, press **Continue** with the fields empty and check that the error is in English. Type a fictitious value in **Street**, switch to ES and back to EN: the value and the step must be kept. The **Use test data**, **Save draft** and **Back to chat** buttons correspond to **Usar datos de prueba**, **Guardar borrador** and **Volver al chat**. Testing the language does not require saving an application.
6. **Traces:** run a new query and open **View latest trace**. Check that destinations, details, numbers and pagination are in English. In lab mode, **View sensitive values** translates the capture titles; the token, `client_secret`, SVID, dynamic credentials and encrypted/decrypted bodies still show the original value. Switching the language does not extend permissions or reveal data automatically.
7. **Mobile:** check that EN/ES is still visible at the top right and that the chat does not scroll horizontally. The October 20 report verified a 390 px width.

The IBM Verify portal and Grafana keep their own language settings. Switching EN/ES keeps the session and the trace step linked through `?span=`; **restarting Lumen** ends the session and discards conversations, unsaved forms and in-memory captures. [Current results and limits](../runs/20261022T140230Z-workspace-review/README.md); [earlier bilingual check of October 20](VALIDACION.md#interfaz-bilingüe-y-trazas--20-de-octubre-de-2026).

## 5. Test the profiles and expected results

| Step | Reader `lumen-reader` | Writer `lumen-writer` | Supervisor `lumen-supervisor` |
|---|---|---|---|
| Query the catalog | Allowed, SQL RO | Allowed | Allowed |
| Check Vault limits | RO yes; RW/protection no | RO/RW + encrypt/encode yes | RO + decrypt/decode yes |
| Create a five-step application | Denied | Allowed | Denied |
| Read the lab's shared queue | Masked | Masked | Masked until revealed |
| Reveal DNI/IBAN/profile | Denied | Denied | Allowed |
| Read the administrative secret | Denied | Denied | Denied |

As the writer, press **Usar datos de prueba** (*Use test data*), review the five steps for address, plan, identity and payment, tick the review box and save. Write down the generated reference; do not use IDs from historical screenshots. As the reader and the supervisor, open that same application and compare reading and revealing. The shared application queue is a decision of this lab; it is not presented as per-customer/tenant isolation.

## 6. Test the agent's two flows

1. **OBO data:** ask «Consulta las tarifas de electricidad del catálogo de Lumen» ("Look up the electricity plans in Lumen's catalog"). The trace must include the provider credentials, the scope check, `verify.obo_exchange`, `vault.read` on Database and `mysql.query` with a SELECT. An explicit wording avoids false rejections by some models' scope classifier.
2. **Tavily agent:** use one of the energy searches offered by the UI. It authenticates as `chatbot-research`, reads `secrets/data/tavily` and calls Tavily; it does not delegate the human's SQL permissions for this search.
3. **Scope:** ask «¿Qué tiempo hace hoy en Palencia?» ("What's the weather in Palencia today?") and then «venga» ("go on"). The rejection of non-energy content must hold. A later explicit question about plans is accepted again. The first filter may call the model. When that filter marks the query as out of scope, the short follow-up is resolved without new calls to the model or to Vault; check this in the trace. Providers may classify the first question differently: a textual rejection response alone does not prove that the model was not called.
4. **Blocks:** apply chapter [12](12-bloqueos.md) and repeat an action that worked before. A visible error must correspond to a Vault 403 or to the actual revocation, not just to text generated by the model.

Repeat the catalog and scope checks with **OpenAI**, **xAI** and **Claude**, using the banner between queries. Check that the model changes, the conversation is kept and the selector is locked while a response is in progress. Open another session to check that its choice is independent. For OpenAI and Claude, their respective SPIFFE subjects/roles must appear; for xAI, the dynamic credential. The model traces must show the chosen provider, not just the initial one.

The process health check must list the three options. This checks configuration loading, not inference availability:

```bash
curl --fail --silent --show-error http://localhost:8088/health | \
  jq -e '.status=="ok" and ([.models[].provider]|sort)==["anthropic","openai","xai"]'
```

The banner identifies the provider and the model. The scope classification and the system prompt constrain the conversation; **Vault decides data authorization**, not the LLM. [Guardrails and traces](../ENERGY_SCOPE_AND_SVID.md).

## 7. Stop the manual run

Stop Lumen and the port-forwards with Ctrl+C in their terminals. If you started the manual JWKS publisher, stop only its PID after checking that it belongs to that process. This keeps the data; do not run `remove` as part of a read-only verification.

Full removal is already documented in the [main README](../../README.md), and `./demo.sh remove --dry-run` lets you review its scope. This series explains configuration and verification; it does not require removing an active deployment.

<a id="actualizar-una-instalación-existente"></a>

## Update an existing installation

### Interface, language and trace viewer only

If the providers already work, EN/ES support and the viewer come with the application code: `chatbot/app/`, including `translations_en.json`, and `chatbot/static/`. There are no new `.env` variables, identities or per-language policies. Nor do you need to republish `chatbot/model`.

- **Manual foreground startup:** stop that process with Ctrl+C and repeat section 3 with the updated code and a new bootstrap token. Keep the existing forwards and infrastructure.
- **Startup managed by the launcher:** from the root, run `bash scripts/demo/start.sh`. It updates the copy in `$LUMEN_STATE_DIR/runtime/chatbot`, renews the observability forwards and restarts Lumen. It requires the existing infrastructure to still be running.
- Sign in again and follow the [bilingual checks](#idioma-y-comprobaciones-bilingües). The restart discards the in-memory state; the browser's language cookie and already saved applications remain.

### Catalog of the three providers

You do not need to recreate Vault, users, MySQL or the federations to add the selector. If the three identities already exist:

1. Load the environment from section 1 and check the `LUMEN_*_MODEL` variables from [00](00-entorno.md). An old value in `.env` takes precedence over the default models.
2. Reapply only the bootstrap policy from [04, section 6](04-vault-iam.md#6-política-bootstrap-y-comprobaciones), which now allows reading `chatbot/anthropic` in addition to OpenAI and xAI.
3. Generate the three profile files with [06, section 6](06-xai.md#6-preparar-el-perfil-xai-para-el-catálogo), [07, section 7](07-openai-spiffe.md#7-preparar-el-perfil-openai-para-el-catálogo) and [08, section 6](08-claude-spiffe.md#6-preparar-el-perfil-claude-para-el-catálogo). Do not repeat the sections that create apps, keys or roles.
4. Check the [observability SPIFFE filter](09-observabilidad.md#actualizar-el-filtro-spiffe-de-una-instalación-existente): it must include OpenAI and Claude. Update only that device if it still has the previous filter.
5. Publish the combined catalog with the second block of section 1. Restart only Lumen with the updated code and the block from section 3; the forwards and ngrok keep running.
6. Check health and test the three buttons as described in section 6. If an identity is missing, prepare its chapter first.

The application loads the catalog at startup: changing models/IDs in Vault requires restarting Lumen; switching between already loaded profiles from the banner does not. The initial selection is used when the browser does not yet have a saved preference. Startup synchronizes Claude's public keys with the administrative profile described in [08](08-claude-spiffe.md).

**How Vault decides:** when you select a call to Vault, the small button next to the HTTP status expands its logic and the correlated audit entries. Check one allowed read and one denied read: policies, actor and RAR must correspond to the selected call. Moving to another step closes and discards the previous evidence. [Available data and limits](../../chatbot/OBSERVABILITY.md#cómo-decide-vault).

**Request console:** in each step of a new trace, **Abrir consola de peticiones** (*Open request console*) shows the real, editable request (URL, method, headers/token and body). It includes the LLM's messages, instructions and tools, the Verify/Vault exchanges and an SQL editor for MySQL. **Enviar petición real** (*Send actual request*) executes the call; you can also copy it as cURL or export it to Postman. Tokens are not renewed, and in-memory captures expire after ten minutes. [Usage, effects and limits](../../chatbot/OBSERVABILITY.md#consola-para-repetir-una-llamada-real).
