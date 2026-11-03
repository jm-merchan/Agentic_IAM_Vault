# OAuth token, lease and backend revocation · November 3, 2026

CIBA remains enabled in the active configuration (`enabled=true`, `auth_mode=oauth`).
Provisioning enables it by default; each contract still requires Validator approval.

The UI at `/laboratorio-revocacion` now has four steps: create JWTs and leases,
test the final system, revoke A through `auth/token/revoke-oauth`, then verify
the JWT, original lease and original credential. No lease-revocation API is called.

| Branch | Dynamic credential | Before revocation | After revoking A | Original B control |
|---|---|---|---|---|
| OBO | `database/creds/chatbot-readonly`, 120 s | A/B: new connection and `SELECT 1` succeed | A JWT: 403; original lease missing; MySQL authentication rejected | JWT: 200; original lease active; original SQL login works |
| Client Credentials | `xai/creds/lumen`, 300 s | A/B: xAI `/v1/api-key` returns 200 | A JWT: 403; original lease missing; xAI returns explicit invalid-key authentication rejection (400) | JWT: 200; original lease active; original API key returns 200 |

The [reproducible live controller run](../../../chatbot/docs/oauth-revocation-leases-verification.json)
passed in both modes while the original leases had not expired and the JWTs still
had approximately 599 s and 595 s remaining. Original leases were also confirmed
absent after cleanup, allowing for asynchronous xAI deletion.

The operator passed seven negative checks: unrelated lease metadata, lease listing,
direct lease revocation, business-data access, policy management, token creation
and another issuer's JWT were all denied. Its only added permission is metadata
lookup for the two dynamic role prefixes; application ownership checks restrict
targets to the current session and agent's generated pair.

[Chrome evidence](browser-verification.json) records the final traces observed in
the running UI for MySQL and xAI, including the success message and A/B credential
results. The xAI run was driven through all four browser buttons. The completed
delegated run was already present in the active browser session and was inspected.
Only the lab control JWTs from those runs were revoked during cleanup; login JWTs
were not targeted.

Validation: the full suite passed **672 Python tests and 2 subtests**, followed by
**112 targeted tests** after adding the latency/TTL-rounding boundary case;
**15 JavaScript tests**, static
documentation/notebook checks with no errors, and 44 application/configuration
files identical between source and the restarted managed runtime. `/health`
reports both `ciba_enabled=true` and `oauth_revocation_lab_available=true`.

README files, the lab walkthrough, operator scope, observability documentation and
notebook 6 were updated. The original CLI/slide example retains its documented
direct KV-marker scope; the new lease verifier exercises the extended UI controller:

```bash
bash chatbot/scripts/verify-oauth-revocation-leases.sh
```

Expiry, lookup errors and backend outages cannot produce a complete success result.
Previously returned static secrets and existing SQL connections are outside the
test's scope; the dynamic credentials here are managed and revoked by Vault engines.
