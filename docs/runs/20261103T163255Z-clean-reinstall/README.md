# Clean reinstallation and end-to-end verification · November 3, 2026

The demo was removed and installed again with `demo.sh start`. The fresh
installation and every verification below passed. This is one scripted rebuild;
the earlier manual rebuilds keep their own dated evidence.

[Aggregated results](results.json) · [Completed installation](install.json) ·
[Final health](final-health.json)

## Removal and recreation

The guarded removal inventoried ownership, revoked existing xAI leases before
destroying Vault, and removed **3 namespaces, 10 persistent volumes and 18
managed Verify resources**. An intermediate inventory confirmed zero remaining
demo volumes and Verify resources. The new installation has different namespace
UIDs and **17 new Verify resource IDs**. The difference is deliberate: the
existing real Validator was reused instead of recreating `lumen-validator`.

The private `.env`, source, documentation, presentation, external OpenAI/Claude
federation resources, Verify administration/shared RAR schema and Minikube profile
were preserved. Resources outside the demo inventory were left in place.

Evidence: [removal plan](remove-plan.json), [completed removal](remove.json),
[empty inventory](empty-inventory.json),
[before](before.json), [after](after.json), [new Verify inventory](after-verify.json).

## Verification against the fresh services

| Verification | Result | Evidence |
|---|---|---|
| Application suite | 688 Python tests and 2 subtests passed | [Installation steps](install.json) |
| Trace UI JavaScript | 15 tests passed | [Aggregate](results.json) |
| General business workflows | 137 checks, 54 traces | [Workflow report](workflows/workflows.json) |
| OpenAI federation and inference | 5 checks | [OpenAI](openai.json) |
| Claude federation and inference | 5 checks | [Claude](claude.json) |
| xAI dynamic credentials and expiry | 12 checks | [xAI](xai-expiry.json) |
| Task agents | 12 combinations, 36 checks | [Task agents](task-agents.json) |
| Personal spaces | 12 combinations, 120 checks | [Personal spaces](personal-spaces.json) |
| RAR constraints | 4 cases, 25 checks | [RAR](rar-parameters.json) |
| OAuth revocation API | Delegated and direct scenarios passed | [API report](oauth-api.json) |
| OAuth leases and trace details | Both modes and 7 operator checks passed | [Lease and capture report](oauth-leases-and-captures.json) |
| CIBA with direct OAuth | 13 checks, real approval and consent | [CIBA](ciba-oauth.json) |

The business workflow uses real Authorization Code + PKCE logins for Reader,
Writer and Supervisor, nine permissions per profile, SQL catalog and application
creation, idempotency, masked/revealed data, OBO tools, all three models, Tavily,
guardrails, blocks with existing and fresh JWTs, xAI credential replacement and
revocation, and correlated Tempo traces/Vault audit in Loki. The implementation
is [workflows.py](../../../scripts/manual/workflows.py), with the documented
[PKCE login helper](../../../scripts/manual/oidc-login.sh).

The capture-enabled revocation test issued original MySQL and xAI leases,
authenticated to each final system, revoked A through `auth/token/revoke-oauth`,
and verified A's original lease disappeared and its original credential failed
before expiry. B's original lease and credential still worked. It also checked
operator boundaries, cleanup and owner-only access to fresh captured details.
It did not repeat the Chrome trace walkthrough from the earlier capture report.

CIBA completed the exact request **Lumen contrato b8c0e625 a7a1e0**. Verify's
browser showed the matching completed result. The service test checked commit,
idempotency, JWT and dependent SQL credential revocation, immutable contracted
data and two matching PDF reads by the owner. A new browser PDF download was
not repeated. Authenticated business walkthroughs were exercised through real
PKCE and application services; Chrome also checked the fresh landing/login UI.

## Attempts and fixes

- The [first installation attempt](install-attempt-1.json) stopped at Claude HTTP
  401 because the preserved external issuer still had the previous Vault keys.
  Only the issuer's public inline JWKS were replaced in Claude Console. A fresh
  [exchange and inference](claude-after-key-update.json) passed, and the next
  `demo.sh start` completed every step. Console mode requires this external update;
  exporting public keys alone does not complete it.
- The first CIBA request stayed pending at consent until the Writer session
  expired. It did not complete a contract. A new request completed approval and
  consent and passed the checks above. Selected consent checkboxes still require
  **Continuar / Continue**.
- `configure-contracts.py` now accepts the persisted non-secret
  `LUMEN_CONTRACT_VALIDATOR` input. Precedence is explicit CLI, environment, then
  previous Vault/local selection. Four regression cases cover this boundary.
  The private `.env` preserves the existing real account across teardown.
- The presentation keeps all 47 slides and manual edits. Slide 6 now obtains the
  recreated Reader SCIM ID with `vault kv get -field=user_id` instead of retaining
  an ID from the destroyed installation. All slides were rendered; all other
  slide images are unchanged and notes remain empty.

The [original 09:13 CIBA migration snapshot](ciba-migration-original.json) is
preserved separately so its earlier browser download evidence is not confused
with the post-reinstallation service test.

## Final state and documentation

Vault, MySQL, Lumen, Grafana, Tempo and Loki are healthy. CIBA is enabled with
direct OAuth and the persisted real Validator. The OAuth revocation lab is
available. Database read/write, decrypt and xAI blocks are all inactive. All
59 application/static files match the managed runtime byte for byte.

README and the environment, repeat-installation, CIBA and revocation guides were
updated to reflect the tested behavior. [Static documentation validation](static-validation.json)
checks links and executable blocks; it does not replace the live results above.
Detailed execution logs and credentials remain in private local state. The
JSON reports in this directory contain results, timing and identifiers.
