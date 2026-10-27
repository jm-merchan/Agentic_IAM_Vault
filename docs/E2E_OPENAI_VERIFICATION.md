# End-to-end rebuild — OpenAI SPIFFE

> Historical: this report belongs to the earlier automated cycle. The deployment was later removed for the [manual installation](manual/VALIDACION.md); its traces and screenshots do not correspond to the current cluster.
Real verification on **October 15, 2026**, on Minikube `workshop`, Vault Enterprise `josemerchan/vault-xai:2.1.2-ent` and IBM Verify `merchan.verify.ibm.com`. The resources were deleted, the empty state was checked and the demo was rebuilt from `.env`. The screenshots on this page belong to the new deployment.

Reproducible reference: [notebook 9 — OpenAI/Vault SPIFFE](../9_OpenAI_Vault_SPIFFE.ipynb). [Integration guide](OPENAI_SPIFFE.md). Evidence: `runs/20261015T114709Z-openai-clean/`.

## Teardown and rebuild

`./demo.sh remove --dry-run`, `./demo.sh remove` and `CHATBOT_VERIFY_ACCESS=1 ./demo.sh start` were run. The flag enables additional OBO checks after each user's real sign-in; it does not simulate their identity.

| Check | Result and evidence |
|---|---|
| Verify teardown | 11 resources: four apps, STS, three users and three groups. [Result](runs/20261015T114709Z-openai-clean/remove.json) |
| Kubernetes teardown | The ten demo volumes were removed; zero demo namespaces and zero demo PVs remained. Previous bootstrap deleted; `.env` kept. [Clean state](runs/20261015T114709Z-openai-clean/clean-state.json) |
| Recreated Verify resources | Same 11 names, all with new identifiers. [Comparison](runs/20261015T114709Z-openai-clean/verify-resources-recreated.json) |
| New Vault identity | Different root token, namespaces with other UIDs and new SPIFFE keys. [Comparison without secrets](runs/20261015T114709Z-openai-clean/recreation.json) |
| Automatic startup | `auto` chose OpenAI because both administrative credentials were present. [Stages](runs/20261015T114709Z-openai-clean/start-auto-openai.json) |
| External trust | The OpenAI project, service account, provider and mapping were kept. The project has zero static API keys. [Check](runs/20261015T114709Z-openai-clean/openai-provisioning.json) |
| Public issuer | Discovery/JWKS published; four private paths return 404. [Results](runs/20261015T114709Z-openai-clean/public-route-checks.txt) |

**Scope of "from scratch":** the demo's data and operational resources are recreated. `.env`, the Verify administrative client, the shared RAR schema, Minikube/caches and the administrative trust in OpenAI are kept. Creating that trust initially remains an external prerequisite documented in the notebook; the mapping was not recreated through private dashboard endpoints.

The first startup hit an HTTP 503 from OpenAI and resumed after GET retries were added. Another attempt detected a JWT that was "not valid yet": the VM had fallen about 14 minutes behind during the test. The clock was synced with the host and `caffeinate` was kept running during validation. The next startup finished successfully; the leeway was not widened and TLS/JWT validation was not disabled. [503 attempt](runs/20261015T114709Z-openai-clean/start-transient-503.json) · [Clock skew attempt](runs/20261015T114709Z-openai-clean/start-clock-skew.json).

## Use cases evaluated

| Case | Observed result |
|---|---|
| OpenAI SPIFFE | New JWT-SVID, real token exchange and inference; a second run obtains another credential. Five passing checks |
| Reader | OpenAI queries the catalog and inventory through tools and OBO SQL RO; local write blocked; SQL RW and retrieval of sensitive data get 403 |
| Writer | Prepares the application with Deep Agents/OpenAI; completes five steps and saves with SQL RW, Transit encrypt and Transform encode; cannot reveal |
| Supervisor | Views the masked inbox, retrieves profile/DNI/IBAN with OBO and cannot create applications or obtain SQL RW |
| Permissions | 9/9 paths match for each profile: **27 checks** across SQL, administration, Transit and Transform |
| OBO at sign-in | **20/20 checks** with real users: SQL SELECT, INSERT/rollback boundary and denial of the Tavily secret |
| Autonomous Tavily | Registered agent, Client Credentials, secret in Vault and public results; no user delegation for that secret |
| `block database-read` | The reader gets 403 without changing session; after unblocking, queries work again |
| `block database-write` | Save rejected; zero partial rows. After unblocking, a single application is saved |
| `block decrypt` | Even the supervisor gets 403; after unblocking, the original values are retrieved |
| xAI | Real provider switch, dynamic issuance, inference and rejection of an expired key; 12/12 checks |
| xAI RAR/block | Missing/incorrect RAR denied, previous and new JWT blocked, lease revoked and recovery after unblocking; 8/8 checks |
| Presentation | Light/dark themes, 390 px mobile with no overflow and a served favicon identical to the workspace one |

Reports: [114 application tests + two subcases and verification stages](runs/20261015T114709Z-openai-clean/verify-openai-run.json), [18 infrastructure checks](runs/20261015T114709Z-openai-clean/infrastructure-tests.json), OBO [reader](runs/20261015T114709Z-openai-clean/obo-readonly.json), [writer](runs/20261015T114709Z-openai-clean/obo-readwrite.json), [supervisor](runs/20261015T114709Z-openai-clean/obo-supervisor.json), [OpenAI](runs/20261015T114709Z-openai-clean/openai-inference.json), [dynamic xAI](runs/20261015T114709Z-openai-clean/xai-dynamic.json) and [xAI RAR/block](runs/20261015T114709Z-openai-clean/xai-blocks.json).

## User walkthrough

The reader queries data with OpenAI; the activity panel shows temporary SQL credentials obtained through OBO.

![Reader and catalog/inventory](runs/20261015T114709Z-openai-clean/screenshots/reader-openai-catalog.jpg)

[Reader permissions](runs/20261015T114709Z-openai-clean/screenshots/reader-permissions.jpg) · [Write denied](runs/20261015T114709Z-openai-clean/screenshots/reader-write-denied.jpg) · [Read blocked](runs/20261015T114709Z-openai-clean/screenshots/reader-database-blocked.jpg) · [Read restored](runs/20261015T114709Z-openai-clean/screenshots/reader-database-restored.jpg) · [Tavily](runs/20261015T114709Z-openai-clean/screenshots/reader-tavily.jpg).

The writer asks the agent to prepare Luz Noche and completes the form. Fictitious address, account holder, DNI and IBAN were accepted with Tab; a DNI with an incorrect letter was rejected before moving on. No action signs up for a supply or makes charges.

![Form review](runs/20261015T114709Z-openai-clean/screenshots/wizard-5-review.jpg)

[Preparation by the agent](runs/20261015T114709Z-openai-clean/screenshots/writer-agent-prepares.jpg) · [Tariff](runs/20261015T114709Z-openai-clean/screenshots/wizard-1-plan.jpg) · [Home](runs/20261015T114709Z-openai-clean/screenshots/wizard-2-address.jpg) · [DNI validation](runs/20261015T114709Z-openai-clean/screenshots/wizard-invalid-dni.jpg) · [Payment](runs/20261015T114709Z-openai-clean/screenshots/wizard-4-payment.jpg) · [Save blocked](runs/20261015T114709Z-openai-clean/screenshots/writer-save-blocked.jpg) · [Save succeeded](runs/20261015T114709Z-openai-clean/screenshots/writer-save-success.jpg).

Application `991f9bb8-9255-4582-a015-8cb5cfb0428b` is stored in MySQL with Transit `profile_ciphertext`, `dni_token`, `iban_token` and masked hints. It was checked that the normalized original documents do not appear in the row. [Storage evidence](runs/20261015T114709Z-openai-clean/protected-storage.json) and [zero rows after the blocked write](runs/20261015T114709Z-openai-clean/blocked-save-database.json).

![Supervisor: authorized retrieval](runs/20261015T114709Z-openai-clean/screenshots/supervisor-reveal-success.jpg)

[Writer: retrieval denied](runs/20261015T114709Z-openai-clean/screenshots/writer-reveal-denied.jpg) · [Reader: masked view](runs/20261015T114709Z-openai-clean/screenshots/reader-masked-application.jpg) · [Reader: retrieval denied](runs/20261015T114709Z-openai-clean/screenshots/reader-reveal-denied.jpg) · [Supervisor blocked](runs/20261015T114709Z-openai-clean/screenshots/supervisor-decrypt-blocked.jpg) · [Supervisor without write access](runs/20261015T114709Z-openai-clean/screenshots/supervisor-write-denied.jpg).

The retrieved DNI and IBAN match the original suggestions; after the dialog closes they do not remain in the DOM. The five model call spans contain prompts/responses, and the DNI/IBAN from the form do not appear in those messages. [UI comparison](runs/20261015T114709Z-openai-clean/reveal-ui.json) · [Model and favicon](runs/20261015T114709Z-openai-clean/model-content-ui-checks.json).

<a id="trazas-y-auditoría"></a>
## Traces and auditing

**16 use-case traces, 229 spans and 55 Vault operations** were correlated. Each operation has its request/response pair, including the 403s. The sent JWT, audit JWT, body and response were compared without copying secrets into the report. [Full result](runs/20261015T114709Z-openai-clean/all-ui-observability.json) · [Trace ID index](runs/20261015T114709Z-openai-clean/ui-traces.json).

![OpenAI/SPIFFE/OBO trace](runs/20261015T114709Z-openai-clean/screenshots/grafana-openai-spiffe-obo.jpg)

The catalog/inventory trace is `095ebb9e2bc0f1564f5e53cd328d31ed`, with 21 spans. The supervisor retrieval is `0e41593d38eb8f16182d37877aeafd70`, with SQL RO, Transit decrypt and two Transform decodes. The links in [the OpenAI guide](OPENAI_SPIFFE.md#trazas) open Grafana with the correct time range.

**Issue fixed:** Alloy 1.20.1 lost four raw request events, even though they were present in `kubectl logs`. A line with timestamp `12:23:52.075392321Z` was observed after another one with `12:23:52.075436363Z`, the case described in [grafana/alloy#7076](https://github.com/grafana/alloy/issues/7076). **1.21.0-rc.0** was pinned, which contains [fix #7080](https://github.com/grafana/alloy/pull/7080). When the original logs were reread, the four events appeared in Loki and all 16 traces passed. A [new nine-path test after the upgrade](runs/20261015T114709Z-openai-clean/fresh-after-alloy-fix.json) also passed.

[The earlier diagnosis](runs/20261015T114709Z-openai-clean/audit-gaps.json) is kept; the individual failed reports in `traces/` describe that first pass, not the final result. No values were substituted and no comparisons were relaxed. The dashboard counts unique `request.id` values so that rereading does not inflate the counters. `updateIntervalSeconds: 30` was configured to detect ConfigMap changes by polling; filesystem events had not updated the dashboard. [Behavior documented by Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/#detect-updates-to-provisioned-dashboards-files).

The Alloy version is a release candidate and is pinned explicitly for this lab. The fix does not turn log scraping into immutable storage: a long outage, log rotation or certain reconnections still require a durable sink in production. The raw events contain credentials, per the configuration requested for the lab; the public JSON reports include only metadata and booleans.

![Four unique supervisor retrieval requests](runs/20261015T114709Z-openai-clean/screenshots/grafana-supervisor-audit.jpg)

## Reproduction and final state

```bash
./demo.sh remove --dry-run
./demo.sh remove
CHATBOT_VERIFY_ACCESS=1 ./demo.sh start
./demo.sh verify --provider openai
# Sign in with each user and walk through the cases above.

# Regression of the xAI alternative:
./demo.sh start --provider xai
./demo.sh verify --provider xai
bash chatbot/scripts/test-xai-block.sh
./demo.sh start --provider openai
```

`start` keeps the blocks; the test restores all of them with `unblock`. `remove` also deletes the cluster traces. The workspace screenshots and reports remain as dated evidence. The external OpenAI resources were kept throughout the cycle. The notebook is a staged reference with Bash cells, without outputs or credentials; `demo.sh` remains the single-step entry point.


**OpenAI · gpt-4.1-mini · SPIFFE JWT-SVID** was left active. The [last installation](runs/20261015T114709Z-openai-clean/final-start-openai.json), the [final verification](runs/20261015T114709Z-openai-clean/final-verify-openai.json), the [final inference](runs/20261015T114709Z-openai-clean/final-openai-inference.json) and its [Tempo/Loki correlation](runs/20261015T114709Z-openai-clean/final-openai-observability.json) passed after switching back from xAI. The four additional blocks are removed; each profile's permissions and RAR still apply. The test's fictitious application is kept to demonstrate reading it.

[Service status](runs/20261015T114709Z-openai-clean/final-status.txt) · [Block status](runs/20261015T114709Z-openai-clean/final-blocks.txt) · [Evidence summary](runs/20261015T114709Z-openai-clean/summary.json) · [Static validation of notebooks, scripts and links](workspace-static-checks.json).

![Final state: OpenAI active](runs/20261015T114709Z-openai-clean/screenshots/final-openai-home.jpg)
