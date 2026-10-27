# Lumen resource removal · October 23, 2026

The demo was removed at the user's request. It was not reinstalled.

- Three Kubernetes namespaces removed: `vault`, `mysql`, and `lumen-observability`.
- Ten persistent volumes removed; all ten hostPath data directories confirmed absent.
- Seventeen Verify resources removed: nine apps, one STS client, four groups, and three test users. A fresh inventory found no remaining Lumen targets.
- xAI leases revoked synchronously before Vault was destroyed.
- Vault Helm release and its labeled cluster roles/bindings absent.
- Local processes and port-forwards stopped; ports 8088, 8443, 13306, 3000, 3200, 4318, 3100, 4040, and 4041 confirmed closed.
- Active operational state removed. The manual session was archived privately under `~/.local/state/lumen-vault-demo/manual-archives/20261023T134636Z-remove/`.

The repository, documentation, historical reports and private logs, `.env`, Minikube profile and cache, shared Verify administrative client and RAR schema, real Validator account, and external OpenAI/Claude federation prerequisites were preserved. `.env` was verified unchanged. The existing removal procedure completed successfully; no manual volume recovery was needed.

The final inventory command recreated empty `vault/` and `pids/` directories through `load_inputs`. Both were inspected and removed with `rmdir` after verification.

[Final result](result.json) · [Initial resource snapshot](before.json) · [Removal plan](remove-plan.json) · [Completed removal](remove.json) · [Post-removal verification](after.json) · [Fresh inventory](after-inventory.json)
