# Removal and manual installation · October 23, 2026

[Guides](../../manual/README.md) · [Removal and recovery](../../manual/13-repeticion-script.md) · [Result](result.json)

The previous Lumen runtime resources were removed, and the demo was reinstalled
by executing the Bash blocks in guides 00–10 and extensions 14, 16, and 17 in
stages. Each block was extracted with `scripts/manual/common.sh`, executed in the
manual session, and checked before proceeding. The log retains its document,
block number, and hash. Installation did not run `demo.sh start` or the automated
`rehearse rebuild/install` cycle; removal and verification used their documented
scripts.

## Removal and recreation

| Resource | Verified removal | New installation |
|---|---|---|
| Kubernetes | `vault`, `mysql`, and `lumen-observability` absent | Three namespaces with new UIDs |
| Storage | Ten PVs deleted and ten hostPath directories absent | Ten PVs with new UIDs |
| Verify | Nine apps, one STS, four groups, and three test users deleted | All 17 resources have new IDs |
| xAI | Leases revoked before destroying Vault | Key issuance, use, replacement, and rejection after revocation verified |

Evidence: [previous inventory](remove-plan.json), [completed removal](remove.json),
[empty state](after-remove.json), [deleted directories](volume-recovery-result.json),
[read-only inventory after installation](after-inventory.json), and
[ID comparison](recreated-resources.json). Namespace UIDs are recorded in
[before.json](before.json) and [after.json](after.json).

The Minikube profile and cache, external OpenAI/Claude accounts and federations,
the Verify administrative client, the shared RAR schema, and the existing real
Validator were preserved. `.env` retains exactly the same bytes and 0600 permissions:
[verification](inputs-preservation.json). The previous manual state was archived
in the private local directory; new secrets remain outside the repository.

## Installation and test results

Vault Enterprise **2.1.2**, with three Raft replicas, TLS, and audit logging;
MySQL Enterprise **8.3.0**, with KMIP/TDE; and the Grafana/Loki/Tempo/Alloy stack
were operational. OpenAI (`gpt-4.1-nano`), xAI (`grok-4.3`), and Claude
(`claude-haiku-5-5`) responded using their Vault identities and credentials.
[Final health](health.json), [ready pods](pods.json), and [block execution log](installation.json).

| Verification | Result | Evidence |
|---|---|---|
| OIDC/OBO workflows, three providers, protected data, access blocks, and traces | 137 checks and 54 traces; all passed | [Workflows](workflows.json) |
| MySQL privileges, bootstrap, and Tavily agent | 18 tests passed | [Infrastructure](infrastructure-tests.json) |
| Task agents | 12 combinations and 36 aggregate checks passed | [Agents](task-agents-verification.json) |
| Personal spaces | 12 combinations and 120 checks passed, including cross-user denials | [Isolation](personal-spaces-verification.json) |
| RAR parameters | Four cases and 25 comparisons passed | [RAR](rar-parameters-verification.json) |
| CIBA contracting | Live approval and nine checks passed | [CIBA](contracts-verification.json) |
| Local manual configuration | 46 tests passed, plus PV recovery filter validation | [Local tests](local-tests.json) |
| Repository documentation and syntax | No errors | [Static validation](static-validation.json) |

Contracting was tested after the user's explicit authorization. The Validator
approved the request `Lumen contrato 5feff551 3cf44e`; the backend created a single
contract, maintained idempotency, and verified two identical downloads of the
[PDF](contrato-verificado.pdf), with its hash recorded in the CIBA report.
[Contracting was then enabled](contracts-enabled.json), and only the Lumen process was restarted.

Inspection of the process environment confirmed that it did not inherit
administrative provisioning credentials: [runtime isolation](runtime-isolation.json).
Temporary access blocks used during testing were disabled:
[final state](final-state.json). [Verification completed](verification-state.json)
with no pending phases.

## Issues found and fixes incorporated

1. **Podman/Minikube stopped and Vault sealed.** The existing profile was started,
   and all three replicas were unsealed with their previous keys before revoking
   leases and removing resources. [Chapter 13](../../manual/13-repeticion-script.md#si-el-clúster-estaba-detenido)
   now includes this prerequisite and explains that `remove --dry-run` does not
   test revocation.
2. **Ten PVs stuck in `Released`.** The provisioner logged
   `identity annotation on PV does not match ours` after its identity changed on
   restart, as described in [Minikube #16140](https://github.com/kubernetes/minikube/issues/16140).
   The inventory, UIDs, `Released` state, `Delete` policy, single node, and exact
   demo paths were validated. Directories were deleted first, followed by the
   PVs, without removing finalizers. The original removal process then completed.
   The [recovery procedure](../../manual/13-repeticion-script.md#volúmenes-released-después-de-reiniciar-minikube)
   retains these checks; its filter was also validated against `Retain`, `Bound`,
   and an unrelated path, all of which were rejected.
3. **Nested Bash in the installer.** `install.sh` selected environment block 3,
   which was intended to open another terminal. In the interactive session, this
   left subsequent commands without the `step` function. The child shell was
   exited, and the correct check blocks were executed. The
   [installer](../../../scripts/manual/install.sh) now selects blocks 4 and 5;
   the installation log excludes the false success recorded for block 3.
4. **Vault path not exported.** The first `configure-rar.sh` attempt failed while
   trying to read `/tmp/vault/config.env`. The [chapter 00 session](../../manual/00-entorno.md#3-crear-una-sesión-de-trabajo-reutilizable)
   now exports `VAULT_ENV_FILE` pointing to the private bootstrap configuration.
   The session was regenerated, variables used for reads were restored, and
   Verify setup was completed. [Chapter 03](../../manual/03-verify.md) explains
   recovery, and a test was added to check that a child process receives the
   correct path.
5. **Extension prerequisites.** Chapters
   [16](../../manual/16-espacios-personales.md) and
   [17](../../manual/17-contratacion-ciba.md) link to the required Python runtime
   installation. CIBA uses `guided-run.sh` to load `.env` and the bootstrap
   configuration in a new terminal. The corrected setup was rerun without
   creating another client or losing the selected Validator.
6. **Processes terminated when the executor session closed.** Closing the
   provisioning terminal stopped Lumen and several supporting processes despite
   `nohup`. The same saved commands were relaunched in independent sessions with
   private logs. Health, ports, public JWKS, and the absence of administrative
   credentials in Lumen were checked again. [Recovery log](process-recovery.json).
   Chapter 13 explains the difference between SIGHUP and the executor cleaning
   up its process tree.

Claude was already configured with `LUMEN_CLAUDE_SYNC_MODE=console`. Only the
existing issuer's public JWKS were updated through Chrome, and the complete saved
JSON was compared with the new Vault's keys. The rule, permissions, JTI protection,
and one-hour maximum lifetime were preserved. [Synchronization evidence](claude-console-sync.json)
and [public keys](claude-jwks.json). Subsequent tests verified issuance,
inference, replay rejection, and audience restrictions. The Claude administrative
API was not attempted during this run.

## Evidence scope

Functional checks use live services and lab accounts; the 46 configuration tests
are local. Static validation checks syntax, links, notebooks, and the integrity
of existing screenshots. The full application test suite was not rerun, and no
new comprehensive visual review was performed.

Chrome was used for the JWKS update and to check that Lumen displayed the catalog
and allowed Claude to be selected. Login through Chrome was not completed in this
session. PDF download and hash verification were established at the backend;
neither the browser-downloaded file nor its visual rendering was verified.

Private logs retain failed attempts and their recovery. The block log records
successful executions, including repeated reads and idempotent steps; its count
does not represent the number of unique steps.

Local endpoints at completion: [Lumen](http://localhost:8088),
[Grafana](http://localhost:3000/d/lumen-iam), and
[Vault](https://127.0.0.1:8443/ui). Manual processes and port-forwards were left
running; they depend on Podman and Minikube remaining active.
