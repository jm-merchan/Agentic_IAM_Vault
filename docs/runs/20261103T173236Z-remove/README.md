# Demo removal · November 3, 2026

Removal completed after the earlier clean reinstallation and verification.
The demo was not reinstalled again.

- Removed 3 namespaces, 10 persistent volumes and 17 managed Verify resources.
- Revoked the dynamic xAI leases before destroying Vault.
- Confirmed zero demo namespaces, volumes and managed Verify resources remain.
- Confirmed no listeners remain on ports 8088, 8443, 13306, 3000, 3200, 4318, 3100 and 4040.
- Removed operational state and archived the stopped manual session privately.
- Preserved `.env`, source, documentation, the presentation, external OpenAI/Claude federation, shared Verify administration/RAR resources and the Minikube profile/cache. The real Validator account was kept. The `.env` and presentation hashes are unchanged.

[Initial plan](remove-plan.json) · [Completed removal](remove.json) ·
[Launcher result](remove-run.json) · [Empty final inventory](after-plan.json) ·
[Verification](verification.json)

The evidence contains identifiers and results. Credentials and private logs remain
outside this directory.
