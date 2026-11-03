# Revocation trace inspection · November 3, 2026

The revocation controller recorded operation metadata but omitted detailed HTTP
and SQL captures. As a result, the trace page could offer **View sensitive values**
while returning no captured values. The embedded lab diagram also disabled inspection.

Fresh traces now keep detailed evidence in the existing ten-minute, session-owned
memory store when `LUMEN_TRACE_VAULT_RAW=1`:

- Verify: actual token request, HTTP Basic authentication and response.
- Vault workload access: actual JWT request and credential/lease response.
- xAI: original API-key request and actual success or authentication-error response.
- MySQL: original dynamic login, prepared/executed query and result or driver error.
- Operator calls: actual payload, response and headers with the bearer redacted.
  These calls are inspectable but cannot be replayed from the request console.

The embedded flow and trace page use the same inspection endpoint. No operator
credential enters captures or browser templates. Exported revocation spans still
contain metadata only. Existing traces cannot recover bodies that were never captured.

[Live verification](../../../chatbot/docs/oauth-revocation-capture-verification.json)
passed in both branches, including lease/backend revocation and cleanup. It checked
**19 delegated and 17 direct call captures** through the real inspection endpoint,
requiring an authenticated owner, nonempty sections, no-store responses and the
expected replay templates. The report contains only identifiers and check results.

[Chrome verification](verification.json) records the fresh direct trace
`83e891b26e46b7baf71b3500b7221a30`. In the running lab, step 4's xAI HTTP 400
response opened under **Respuesta HTTP real** with its body visible and without
the empty-capture notice. The browser's active lab pair was left available for
inspection with its normal short credential lifetime.

Validation passed: **683 Python tests and 2 subtests**, **15 JavaScript tests**,
static documentation/notebook validation, source/runtime equality for the changed
application files, and `/health`. The managed application was synchronized and
restarted. The lab guide, observability documentation and generated notebook 7
reflect the new capture behavior.

Reproduce the live controller and inspection checks:

```bash
LUMEN_REVOCATION_CAPTURE_CHECK=1 bash chatbot/scripts/verify-oauth-revocation-leases.sh
```
