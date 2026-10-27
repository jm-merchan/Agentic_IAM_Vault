# Lumen end-to-end verification

**Historical, 10/14.** This deployment was removed. The [OpenAI rebuild of 10/15](E2E_OPENAI_VERIFICATION.md) covers the later state and screenshots.

Run on **October 14, 2026** on Minikube `workshop`, IBM Verify `merchan.verify.ibm.com` and Vault Enterprise with the `josemerchan/vault-xai:2.1.2-ent` image. Evidence: [`runs/20261014T162141Z/manifest.json`](runs/20261014T162141Z/manifest.json).

**Two real teardowns** were performed, along with a full installation from an empty state, a later reconciliation of the OAuth configuration and interface tests with the three users. The issues detailed at the end were fixed during the run. The screenshots belong to this deployment; none from the removed resources were reused.

The button check was extended on October 15 to cover nine SQL, Transit and Transform paths. See [the matrix and its current screenshots](PERMISSION_PROBES.md). The three-path screenshots in this report keep the result of the October 14 version.

## 1. Teardown and rebuild

```bash
./demo.sh remove --dry-run
./demo.sh remove
CHATBOT_VERIFY_ACCESS=1 ./demo.sh start
./demo.sh verify
```

`CHATBOT_VERIFY_ACCESS=1` enables the OBO checks when each user signs in through OIDC. The passwords are retrieved from Vault; they are not included in this report.

| Check | Result | Evidence |
|---|---|---|
| Kubernetes teardown | Zero demo namespaces and zero PVs left | [Clean state](runs/20261014T162141Z/final-clean-state.json) |
| IBM Verify teardown | Three application clients, one STS, three groups and three users deleted | [Real teardown](runs/20261014T162141Z/final-remove.json) |
| Preservation | `.env` unchanged; administrative client, unrelated resources and Minikube profile kept | [Scope and inventory](runs/20261014T162141Z/resources-after-start.json) |
| Rebuild | Ten new Verify IDs, ten new PVs and namespaces with new UIDs | [Recreated resources](runs/20261014T162141Z/recreated-resources.json) |
| Installation | 21 stages completed; Vault initialized/unsealed and MySQL with KMIP | [Clean startup](runs/20261014T162141Z/start.json) |
| OAuth reconciliation | Full idempotent startup, keeping the saved application | [Second startup](runs/20261014T162141Z/start-reconciled.json) |
| Final state | Vault 3/3, MySQL and four observability services available | [Local state](runs/20261014T162141Z/services-status.txt) · [Vault](runs/20261014T162141Z/vault-pods.json) |

Before the workflows started there were **three tariffs, three servers and zero applications**. The inventory is also created on an empty installation. [Initial counts](runs/20261014T162141Z/database-before-workflows.json).

## 2. Sign-in and permissions of the three users

The three users really signed in on Chrome through Verify OIDC. Their IDs and groups are those of the new deployment: [users](runs/20261014T162141Z/users.json).

| Profile | Read catalog/inventory and masked inbox | Save application | Reveal DNI/IBAN and profile | Administrative secret |
|---|---|---|---|---|
| `lumen-reader` | Allowed | UI block and Vault RW denied | Vault Transit denied | Denied |
| `lumen-writer` | Allowed | Allowed: real INSERT | Vault Transit denied | Denied |
| `lumen-supervisor` | Allowed | UI block and Vault RW denied | Allowed: Transit + Transform | Denied |

**20 OBO checks** were completed: [reader, 6](runs/20261014T162141Z/obo-readonly.json), [writer, 8](runs/20261014T162141Z/obo-readwrite.json), [supervisor, 6](runs/20261014T162141Z/obo-supervisor.json). Read, write and reveal permissions were checked separately; an expected denial counts as a passing test.

![OIDC sign-in for the new client](runs/20261014T162141Z/screenshots/02-oidc-consent.jpg)
![Reader queries catalog and inventory](runs/20261014T162141Z/screenshots/03-reader-agent.jpg)
![Reader: write blocked](runs/20261014T162141Z/screenshots/06-reader-local-block.jpg)
![Writer: reveal denied by Vault](runs/20261014T162141Z/screenshots/19-writer-reveal-denied.jpg)
![Supervisor: SQL RO allowed, RW and administration denied](runs/20261014T162141Z/screenshots/26-supervisor-limits.jpg)

## 3. Real application and data protection

The writer prepared **Luz Noche** with the agent and completed the five steps: tariff, home, account holder, payment and review. A single fictitious application was saved: `8cd2a9fd-190b-4864-afce-1bbc41b6f97f`.

The following were verified: Tab to accept suggestions, Shift+Tab without filling in, preservation of manually typed text, rejection of an incorrect DNI, valid DNI/IBAN checks, the suggestion button and regeneration when opening a new draft. The data is synthetic; the IBAN uses the lab bank `0000`. [Interface checks](runs/20261014T162141Z/form-ui-checks.json).

![Application prepared by the agent](runs/20261014T162141Z/screenshots/09-writer-prepare.jpg)
![Address and Tab navigation](runs/20261014T162141Z/screenshots/11-form-address.jpg)
![DNI validation](runs/20261014T162141Z/screenshots/12-form-invalid-dni.jpg)
![Review before saving](runs/20261014T162141Z/screenshots/17-form-review.jpg)
![Persisted application](runs/20261014T162141Z/screenshots/18-writer-saved.jpg)

MySQL keeps the profile encrypted with Transit and opaque DNI/IBAN tokens. The four tables are encrypted at rest and the KMIP plugin is active. Reader and writer reads are masked; the supervisor retrieved the exact original values through Vault. When the dialog closed, the revealed values disappeared from the DOM. [Persistence](runs/20261014T162141Z/protected-storage.json) · [Reveal](runs/20261014T162141Z/reveal-ui-checks.json).

![Reader: masked inbox](runs/20261014T162141Z/screenshots/21-reader-masked.jpg)
![Supervisor: retrieval of the fictitious data](runs/20261014T162141Z/screenshots/27-supervisor-reveal.jpg)

The form was checked at **390 px**, in light and dark mode, with no horizontal overflow. These two screenshots show a second unsaved draft, with suggestions different from the persisted application.

![Mobile form, light](runs/20261014T162141Z/screenshots/15-form-mobile.jpg)
![Mobile form, dark](runs/20261014T162141Z/screenshots/16-form-mobile-dark.jpg)

## 4. Autonomous agents and dynamic xAI

The registered search agent obtained Tavily from Vault and ran a real search. It was verified that it cannot obtain SQL credentials or administrative secrets. The xAI identity uses Client Credentials and `xai/creds/lumen`, with a 300-second dynamic key.

Initial issuance, reuse of the same lease and replacement **before expiry** due to insufficient remaining validity were observed. The plugin declares the lease non-renewable: the application requests a new one and does not try to renew it. The 12 xAI tests include real inference, access limits, rejection of an expired key and revocation of its lease. [Lifecycle in the application](runs/20261014T162141Z/xai-runtime.json) · [Dynamic tests](runs/20261014T162141Z/xai-dynamic-verification.json).

![Tavily search by the autonomous agent](runs/20261014T162141Z/screenshots/07-tavily.jpg)
![Replacement of the temporary key](runs/20261014T162141Z/screenshots/08-xai-rotation-trace.jpg)

## 5. Traces, prompts and audit log

**20 traces, 185 spans and 37 Vault operations** were correlated. For each operation, `traceparent`, request ID, namespace, policies, sent body, JWT and response were compared with the authenticated raw copies in the audit log. That is 74 request/response events after deduplicating internal copies. All checks passed. [Correlation report](runs/20261014T162141Z/traces.json).

The reader's final query produced two model calls. 12 content fields were compared between the local viewer and Tempo: input/output messages, tools, arguments and results, parameters and user text. The full DNI, IBAN, name, address, email and phone number from the form were not in those messages. Vault raw traces do keep their exchanges because of an explicit lab setting. [Content check](runs/20261014T162141Z/model-content.json).

![Model input text](runs/20261014T162141Z/screenshots/25-model-input.jpg)
![OBO JWT: user, group, actor and path authorization](runs/20261014T162141Z/screenshots/32-obo-jwt-claims.jpg)
![Reveal: four Vault operations with no denials](runs/20261014T162141Z/screenshots/30-grafana-reveal-audit.jpg)
![Reader: one allowed operation and two denials](runs/20261014T162141Z/screenshots/31-grafana-reader-denials.jpg)

### Links to the verified deployment

The following links include an absolute time range. They require signing in to Grafana as `lumen-admin` (password in Vault at `verify/secrets/chatbot/observability`). Tempo/Loki retain seven days; another `remove` deletes that content. Screenshots and reports remain in the workspace.

| Flow | Tempo trace | Correlated audit log |
|---|---|---|
| Catalog and inventory | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22b123f1c4eb409325b27b2909f8f05a6f%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=b123f1c4eb409325b27b2909f8f05a6f&var-audit_mode=raw) |
| Save application | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%228a28f5caadcebb0576c7ef24265d02f7%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=8a28f5caadcebb0576c7ef24265d02f7&var-audit_mode=raw) |
| Writer: reveal denied | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22b2640481a5089f9b85b6e0d85e088f02%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=b2640481a5089f9b85b6e0d85e088f02&var-audit_mode=raw) |
| Supervisor: reveal | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22b93a149ee494649293b8c1d3a8ff0796%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=b93a149ee494649293b8c1d3a8ff0796&var-audit_mode=raw) |
| Reader: check limits | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%2202e4b62df97ae9259edb8135d81e7aa5%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=02e4b62df97ae9259edb8135d81e7aa5&var-audit_mode=raw) |
| Tavily agent | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%2297cd790adf60665a7f71eae7f2aa045f%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=97cd790adf60665a7f71eae7f2aa045f&var-audit_mode=raw) |
| xAI rotation | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22af3fb267a674b0c091ec601024af2cb6%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=af3fb267a674b0c091ec601024af2cb6&var-audit_mode=raw) |
| Masked query and prompts | [Open trace](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%222fde3c3b0ca8b8f7c1511c7378b0bd8e%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Open logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=2fde3c3b0ca8b8f7c1511c7378b0bd8e&var-audit_mode=raw) |

## 6. Issues resolved during the run

| Finding | Fix and check |
|---|---|
| Inventory missing when installing from scratch | Encrypted table and three sample servers; second teardown/installation and real read verified |
| macOS sleep set the VM clock back | Clock preflight and sync; TLS remains validated |
| Freshly issued JWTs rejected because of `iat`/`nbf` | `clock_skew_leeway=15` in the OAuth profile, same as the client; three sign-ins and 20 OBO checks repeated |
| Unit tests mixed fictitious spans with the demo | Temporary local export and OTLP disabled during pytest |
| Grafana exhausted 768 MiB and the tunnel did not recover | 1536 MiB and a 768 MiB Go target; `launchd` restarts tunnels. Deliberate termination and recovery verified |

![Dashboard recovered after restarting the tunnel](runs/20261014T162141Z/screenshots/33-grafana-restored.jpg)

[Issues](runs/20261014T162141Z/incidents.json) · [Tunnel recovery](runs/20261014T162141Z/forward-recovery.json). The intermediate clock error is documented; it is not included as a passing trace in the 20-trace report.

## 7. Result and updated material

- 74 application tests and two subcases.
- 18 infrastructure and privilege checks.
- 20 OBO checks through the real sessions of the three profiles.
- 12 xAI dynamic secret tests.
- 20 real traces correlated with Vault; form, reveal, Tab and mobile checked visually.

[`demo.sh verify`](runs/20261014T162141Z/verify-final.json) passed after the fixes. The [main README](../README.md), the [Lumen guide](../chatbot/README.md), the [observability guide](../chatbot/OBSERVABILITY.md), the [workspace review](WORKSPACE_REVIEW.md) and notebooks [6](../6_Lumen_Chatbot_Vault_IAM.ipynb), [7](../7_Lumen_Observability.ipynb) and [8](../8_Lumen_Protected_Applications.ipynb) were updated. The old Okta and Verify bootstrap reports are marked as historical.

The published JSON files contain metadata and checks; tokens, keys and raw responses stay in the lab services and in the private state, not in this report. The state was verified on the date shown; retention, a Lumen session restart or a new teardown can change the availability of the live views.
