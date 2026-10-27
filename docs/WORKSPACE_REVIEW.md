# Workspace review

## Final repository validation · October 22, 2026

The [final validation](runs/20261022T161825Z-repo-validation/README.md) adds
the explanation of Vault decisions and checks that the code,
notebooks, documentation and runtime are aligned. It includes the fixes to the Loki
response format and to historical links. Earlier results keep
their date and scope.

## Full review of interface, documentation and services · October 22, 2026

The [detailed review](runs/20261022T140230Z-workspace-review/README.md) replaces the screenshots embedded in active guides and
four notebooks with images of the current interface. The manifest keeps the
page, date and hash of each screenshot. Old reports keep their date and
their images as historical evidence.

The following were fixed: the link to the latest trace in Applications, keeping the trace
step when switching ES/EN, action names, false rejections by the classifier and the Grafana counter that
failed when it exceeded 500 series. The services, the authorization
matrices and the Chrome walkthroughs were tested again. The linked report contains the
final results, the failed attempts and the exact scope of each test.
**532 Python tests and 2 subtests**, **12 JavaScript tests** and
**137 real checks with 54 traces** passed. **45 screenshots** were reviewed visually.
Chrome's receipt of the PDF is still not demonstrated; it is distinguished from the success
of the endpoint and from the integrity already checked in the backend.

## Reinstallation and verified fixes · October 22, 2026

After the local review described below, the requested teardown and
reinstallation were run. [Report and evidence](runs/20261022T122934Z-full-e2e/README.md).
The final suite passed **513 Python tests and 2 subtests**, plus **12 JavaScript
tests** and **137 real checks**. The changes are published in
the runtime; the agent, personal space, RAR and CIBA matrices also passed.

| Finding during the real run | Fix and evidence |
|---|---|
| The Claude administrative API returned 404 despite a valid OAuth sign-in | Preflight of real access to the issuer/rule and an explicit `api`/`console` mode. The latter exports only public JWKS and leaves the sync pending; the real inference is still mandatory. The keys were updated and compared in the console. |
| An old, disabled PDF client no longer exposed `clientId` | Teardown accepts only the exact name, description, template and states of that resource; it still protects the administrator client. The CIBA configurator tolerates the missing field. Tests for accepting it and rejecting unrelated resources. |
| Three HTTP test doubles lacked the `request` that trace capture needs | `httpx.Response` responses with an associated request are used. Full suite with both capture modes enabled. |
| The guardrail rejected the harness's technical phrase that named `buscar_en_web` | A natural request about solar self-consumption is used, and scope, the real call and HTTPS sources are checked separately. The failed attempt is kept; the guardrail is not modified. |
| NiceGUI passed the client to the keyword-only parameter of `Timer.cancel` when closing pages | Explicit callback with no arguments. The test with a real client reproduced the `TypeError` before the change and passes after it; runtime updated. |

The backend CIBA download produced two identical PDFs and the contract persisted
after a restart. Receipt of the file in Chrome is still not confirmed:
the button generated a correct trace, but the automation timed out waiting for the
download event. The report distinguishes that limitation from the backend tests.

<a id="revisión-del-22-de-octubre-de-2026"></a>
## Review of October 22, 2026

Local review of the application, installers and documentation. The
OIDC/OBO, model, personal space and CIBA contracting flows were checked against their
policies and tests. The changes were applied to the repository files;
no Verify, Vault or MySQL resources were deployed or modified.

| Inconsistency | Fix and check |
|---|---|
| `pytest` from the root did not find `app` and failed during collection | `pytest.ini` sets the application path and the tests directory. The full suite runs from the root. |
| A 429/500/503 response when reading the catalog was interpreted as an absence of models | Startup fails with a diagnosis and revokes the bootstrap. The optional catalog is kept only for 403/404. Simulated HTTP tests of the five cases. |
| The periodic CIBA cleanup could empty the snapshot or delete a request while it was being finalized | The cleanup respects the operation lock; polling checks expiry again when it acquires it. Tests for concurrent cleanup and expiry during the wait. |
| Cancelling a CIBA task left the request in `waiting` with sensitive data and an exchange that might have been consumed | Both the start and the polling move to `error`, clear the state and propagate the cancellation. Both interruptions are checked. |
| A pending PDF download kept a reference to a removed session; it could also deliver the PDF after expiry | The session identity and its validity are checked after the wait and before delivering the document. HTTP tests for removal and expiry. |
| User creation used a temporary password with `pwdReset=false`; losing the POST response could leave a credential different from Vault's | Users are created with `pwdReset=true` and the activation PATCH is completed on resume. The simulator reproduces a completed POST with a lost response and verifies the three passwords without recreating users. Manual and script use the same procedure. |
| Notebook 10 kept 11 executed cells and prevented the suite invoked by `demo.sh` from completing | All commands and metadata were kept; outputs and counters were cleared after saving a complete private copy. |
| The installer announced that the Claude JWKS still had to be synced after it had done so | The final message reflects the completed sync and asks you to run the functional verification. |
| Static validation did not cover the main README, `demo.sh`, the whole application or the notebooks | `scripts/manual/validate.py` includes those files and detects saved outputs. A case with defective files checks that all four problem types are detected. |
| The documentation mixed the initial provider with startup requirements, the OBO JWT with the native CIBA token and historical results with the current state | Main README, chatbot, Verify, Okta and index/manual updated. |

The tests for the new issues were first run against the earlier
code and reproduced the catalog, CIBA concurrency/cancellation,
download session and lost user-creation response failures.

The copy of the notebook with its original outputs is outside the repository, in
`~/.local/state/lumen-code-review/20261022T122212Z/10_OAuth2c_Verify_Vault.ipynb`,
with `600` permissions. Original SHA-256:
`cf2299241cacf147a025278de1e76a7d8d6cd1574d9cd473cdf962c57ff4914b`.
Git history was not rewritten and the cells were not executed.

### Local validation

Result: **505 Python tests and 2 subtests passed** (168.44 s), **12 JavaScript
tests passed** and zero errors in static validation. The Python environment
contains 124 compatible packages. The seven YAML configurations were also parsed
with no duplicate keys, as were the five configuration/application JSON files.

The reproducible commands are in the [README](../README.md#revisión-y-pruebas-locales).
The syntax, links and notebooks report is in
[validacion.json](manual/validacion.json). Dependency compatibility was also checked
with `uv pip check`, and the archived Terraform with
`terraform fmt -check` and `terraform validate`, using the providers already installed
in `~/.local/share/okta-vault-agentic/data`.

These checks do not include a deployment, inference, a real CIBA approval,
tests against the tenants or a visual review in a browser. The Python UI tests
use the local NiceGUI simulation. The following historical reports
keep their dates and scope; they do not demonstrate these changes as deployed.

## Review of October 14 and 15, 2026

The active path is **Lumen + IBM Verify + Vault Agentic IAM**, with MySQL/KMIP, Transit/Transform, dynamic xAI, Tavily and observability. Okta and the old payments exercise are not part of the automated run.

## October 15 extension

The OpenAI branch uses SPIFFE JWT-SVID and token exchange, keeping OBO for data and xAI as an alternative. [Notebook 9](../9_OpenAI_Vault_SPIFFE.ipynb) and the [new end-to-end report](E2E_OPENAI_VERIFICATION.md) document the rebuild with 11 Verify resources removed, new SPIFFE keys and the three profiles.

Retries were added only to GET queries against the OpenAI administrative API after an HTTP 503; creations are not repeated automatically. The OpenAI verification exports traces by default; old test reports are removed when a new check starts. `configure-model.sh` routes OpenAI to the SPIFFE flow and no longer asks for a static API key. README references, notebook 7 audit devices and the loss of Alloy lines were fixed with release candidate 1.21.0-rc.0. The following entries describe the original 10/14 review.

## Inconsistencies fixed (October 14)

| Finding | Fix |
|---|---|
| Notebook 1 ran `minikube delete --all`, deleted `/tmp/vault`, initialized without checking state and killed the process on 8443 | `demo.sh` adopts or creates, checks initialization and ports, and keeps keys; destructive cleanup is a separate and explicit operation (`remove`) |
| Vault port-forward on `0.0.0.0` and recovery keys dependent on `/tmp` | New tunnels on `127.0.0.1`; persistent bootstrap in the state directory |
| Helm status `failed` due to an SSA conflict on the injector `caBundle` | Same version/configuration with Helm 4 client-side apply; revision 3 ended up `deployed` |
| The deployment depended on a local image and on the plugin source code | Published image `josemerchan/vault-xai:2.1.2-ent` (AMD64/ARM64); pulled directly from Docker Hub, with no local build |
| An empty installation stopped when reading `kmip/config` before creating it | HTTP 404 starts the configuration; permission/server errors stop the process without modifying it. Six regression tests |
| Tunnels that were still listening but pointed to deleted pods were reused | `start` renews the tunnels for the expected context/namespace/path under `launchd`; it rejects unrelated processes. Six regression tests |
| Notebook 1 mounted xAI at the root, but Lumen uses `verify/xai` | Global catalog; Lumen's engine mount/configuration in `verify` |
| Notebook 2 reinstalled UDFs, regenerated certificates, restarted MySQL and simulated a KMIP outage in the normal flow | Idempotent deployment; keeps certificates/data; check that `keyring_okv` is active |
| Notebook 3 depended on a nonexistent `5_Payments_App.ipynb` app and on sample SQL passwords | Notebook focused on the Lumen RO/RW configuration; the existing root connection and roles are kept outside the flow |
| 53 cells with persisted outputs in notebooks 2–4, including credential reads | Reference notebooks regenerated without outputs; originals kept privately outside the workspace |
| Active reference to `secrets/xai` as a requirement and confusion between the existing role's TTL and the requested TTL | The static requirement is removed; explicit 300 s request. Existing role kept; 5 min/10 min only as creation values |
| xAI revocation by prefix in a normal cell | Test with a disposable key and revocation of only its lease |
| Specific `vault-authn-entry` ID inside `02-verify-apps.sh` | OIDC template without credentials or instance ID in `verify/config/oidc-template.json` |
| Base Vault configuration depended on a saved human session | `configure-base.sh` configures RAR/profile without a prior human sign-in; OBO still uses a real sign-in when running the application |
| Research kept the template's Authorization Code and refresh tokens | Search client limited to Client Credentials |
| The Verify notebook could overwrite current scripts with old embedded copies | Uses workspace files and checks syntax; does not materialize them again |
| Documentation stated three audit devices after xAI was added | Four: one HMAC output and three filtered raw ones |
| The default CA in Python pointed to `ca.crt`, different from the bootstrap | Consistent `vault.ca` fallback; normal runs use the explicit state path |
| The supervisor report could overwrite the reader's because they share the SQL RO role | Separate `obo-supervisor.json` report |
| Transform could produce audit copies with the same ID on two nodes; the internal copy without `auth` caused false failures | The authenticated raw copy is selected and the full JWT, body and response comparisons are kept; three regression tests |
| `nohup` did not keep processes alive after the automated run ended; `launchd` could not access the code on Google Drive | User services with a runtime copy outside CloudStorage; macOS permissions are not widened |
| `.gitignore` excluded `.hclic`, but not `vault.hclic` | `*.hclic` pattern; `.env`, import temporaries and the KMIP key excluded |
| `.env` kept old `VAULT_TOKEN`, `VAULT_ADDR` and `VAULT_CACERT` values, although they were not preflight requirements | Those entries removed; the initial load ignores inherited Vault credentials and later stages load the private bootstrap generated after init/unseal |
| Inventory used by the agent had no table on an empty installation | `01-database.sh` creates the encrypted `test_encryption` table and three fictitious servers if it is empty; both SQL credentials test reading it |
| macOS sleep left the VM clock behind and broke TLS/JWT | Preflight checks the Minikube clock; VM clock sync and sleep are documented |
| Freshly issued JWTs rejected with an almost identical clock | OAuth profile with `clock_skew_leeway=15`, same as the client; six supervisor OBO checks repeated successfully |
| Unit tests added fictitious spans to the demo file | `tests/conftest.py` isolates the local exporter and disables OTLP during pytest |
| Grafana exhausted 768 MiB and its tunnel stayed stopped | 1536 MiB limit, 768 MiB Go target and port-forward recovery through `launchd`; real reconnection verified |
| Screenshots, Trace IDs and counts belonged to removed deployments | Active documentation linked to the dated run; notebooks without old runnable sample IDs |

## Secrets and state

`.env` keeps only external entries and initial passwords, with mode 600. The private Vault bootstrap is generated after init/unseal. The application does not inherit the root token. A hash check confirmed that `.env` did not change between teardown and rebuild.

The real deletion was run twice: three Kubernetes namespaces, ten PVs and ten Lumen resources in Verify. The empty state and the preservation of the administrative client and unrelated resources were verified. The Minikube profile and caches remain. Scope: [remove](../README.md#volver-a-empezar-desde-cero).

## Validation and limits

The original evidence is gathered in the [10/14 report](E2E_VERIFICATION.md); the next cycle's evidence is in the [10/15 OpenAI report](E2E_OPENAI_VERIFICATION.md). Later checks, including the EN/ES check of 10/20, are linked in [VALIDACION](manual/VALIDACION.md). It describes both cycles, the fixed issues, the later reconciliation startup, the real sign-ins and their results. It does not certify a future state: a new `remove` deletes the data and traces of this run.

## Evidence of the full walkthrough

See the [historical results and screenshots of 10/14](E2E_VERIFICATION.md) and the [immutable run directory](runs/20261014T162141Z/manifest.json). Each screenshot and report under `chatbot/docs/` demonstrates the dated run that produced it. The active guides distinguish that evidence from the procedures for checking the current state.

## Reference sources

- [IBM Verify for Agentic IAM](https://developer.hashicorp.com/vault/ai/iam/providers/verify).
- [Agent registry](https://developer.hashicorp.com/vault/ai/iam/setup-agent).
- [OAuth Resource Server and clock leeway](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server).
- [Vault on Kubernetes](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/helm/run).
