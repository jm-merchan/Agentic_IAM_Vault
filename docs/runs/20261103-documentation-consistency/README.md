# Documentation consistency · November 3, 2026

README, installation guides, operating instructions, observability and generated
notebooks were compared with the current application and provisioning code.
This review updates instructions and references; it does not provision resources
or repeat the live CIBA approval, model inference or OAuth revocation runs.

## Corrections

| Area | Result |
|---|---|
| CIBA | Provisioning enables contracting by default. The live test records evidence; `--enable` re-enables an explicitly disabled setup. A usable, separate Validator and approval/consent remain necessary. |
| Credential flow | CIBA presents Verify's access JWT directly to Vault and cleans up with `auth/token/revoke`. The lab uses a separate native operator and `auth/token/revoke-oauth`, with issuer/jti and a duration `exp`. |
| Manual startup | Chapter 10 now prepares the issuer-limited operator as well as bootstrap and metadata-inspection credentials. The documented startup remains Bash block 4, preserving the rehearsal's block references. |
| Revocation UI and CLI | Both delegated and direct access are documented. Common A=403/B=200 checks are distinguished from CLI-only operator/SQL checks and their different credential scopes. |
| Clock errors | Duplicate operating-guide sections are consolidated. The 5 s manual preflight, 60 s launcher check, 30 s runtime diagnostic and 15 s JWT leeway have separate purposes. |
| Removal and capture | Documentation reflects retained evidence folders and the revocation operator's exclusion from raw capture. Revocation and contract audit routes use the protected output. |
| Historical evidence | October runs and screenshots retain their dates. November live evidence is linked separately from the checks repeated here. |
| Notebooks | Ten active notebooks now match seven generators. Two generators were updated for the new flows. Other code-cell differences were translated comments and display messages, with the executable control flow unchanged. |
| Notebook tests | Two assertions still expected Spanish messages from the English OAuth2c generator. They now verify skipped-refresh behavior and rejection of a non-authorization failure independently of those translated sentences. The complete suite was repeated afterwards. |

## Checks repeated in this review

| Check | Result |
|---|---|
| Complete Python suite | 653 passed, 2 subtests passed |
| JavaScript suite | 15 passed |
| Notebook regeneration | 10/10 match their generators; generated in a temporary workspace |
| Manual operator startup | Documented commands executed against a synthetic CLI; rendered policy matches the source template |
| Documentation syntax, local links, screenshots and source | 40 documents, 290 Bash blocks, 775 local links, 11 notebooks and 46 screenshot records; no errors in [static validation](static-validation.json) |
| Live readiness and source/runtime comparison | Read-only checks recorded in [verification.json](verification.json) |
| PowerPoint content | Text of all 42 slides and notes inspected for retired CIBA/token instructions. The four lab slides describe the CLI variant and remain technically consistent; no layout edit or new render was performed. |

Detailed records: [notebook alignment before](notebook-generation-before.json),
[final notebook alignment](notebook-generation.json),
[manual startup check](manual-startup-check.json).

The intermediate notebook regression run had 86 passes and two failures from
those message assertions. The final complete run passed 653 tests and two
subtests in 215.62 seconds. No application authorization code was changed by
this review.

## Earlier live evidence

- [CIBA direct OAuth migration](../../CIBA_OAUTH_VERIFICATION.md): 13 live checks,
  including Validator approval and consent, direct JWT authorization and SQL/PDF checks.
- [OAuth API runner](../../../chatbot/docs/oauth-revocation-verification.json):
  20 checks across delegated and direct access.
- [OAuth UI lab](../../../chatbot/docs/oauth-revocation-ui-verification.json):
  Chrome walkthrough and a separate live controller check, with operator denials and cleanup.
- [Writer clock diagnosis](../../../chatbot/docs/writer-clock-verification.json):
  the recorded 2,005 s offset and the subsequent successful browser query, without ACL changes.

These records retain their original timestamps. They do not imply a new approval,
reinstallation, browser walkthrough or revocation during this documentation review.
