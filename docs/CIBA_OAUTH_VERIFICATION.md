# CIBA direct OAuth verification · November 3, 2026

The live run completed at **09:13:43 UTC** against Vault **2.2.0+ent**, namespace
`verify`, and IBM Verify. [Machine-readable results](../chatbot/docs/contracts-verification.json)
record **13 passing checks** for `contract-ciba-oauth`.

## Credential flow

1. Writer saves one fictitious draft through regular OBO.
2. The dedicated CIBA-only client requests the Validator's confirmation and five RAR details.
3. After authentication and consent, Verify returns a signed access JWT:
   `sub=64300857U3`, `actor-token.sub=b12262f4-9a7c-407b-8811-e3b6cc316d78`.
4. Lumen sends that access JWT in `X-Vault-Token` to the engines and KV.
   Vault resolves human and actor aliases and intersects human policy, actor ceiling and RAR.
5. A leased MySQL user with EXECUTE on `lumen_contracts.formalize` commits the contract.
   Lumen publishes its PDF only after that commit.
6. Lumen calls `auth/token/revoke` with the access JWT as both credential and target.
   Vault rejects subsequent use of the JWT and the SQL login stops working.
7. The owning Writer retrieves the committed PDF through regular OBO.

There is no CIBA login at `auth/ciba-contract/login` and no intermediate native
Vault token. The owned legacy auth mount was removed. The existing native tokens
for startup configuration and read-only agent inspection keep their separate roles.

## Verified boundaries

- Ordinary ID token and Writer OBO cannot obtain the contracting SQL role.
- The CIBA client rejects Client Credentials.
- Writer's ordinary SQL user cannot update contract status, call the procedure or read encrypted PDFs.
- No contract exists while CIBA is pending.
- The signed RAR denies another PDF owner.
- Revocation ACL rejects native Vault token targets.
- SQL retry produces the same contract and hash.
- OAuth JWT revocation also revokes its SQL credential.
- Exactly one committed `contratada` row exists.
- Two owner reads return the same PDF, matching its recorded SHA-256.
- The contracted draft rejects ordinary Writer updates.

Successful confirmation trace: `3adc2ffd48405e47e7816dc1c88bd053`.
Contract: `42999540-0675-49db-bf6a-99bde31e2325`.
Actor entity: `bf4efa9b-28a7-558b-f5c5-74210d48f342`.

The protected backend PDF and claim diagnostics remain in private local state.
After enabling and restarting the managed runtime, Chrome showed Writer's
**Contratar** buttons and the persisted new contract. Clicking its PDF button
produced `lumen-contrato-42999540-0675-49db-bf6a-99bde31e2325.pdf`, **9.2 KB · Done**
in Chrome's download history. The SHA-256 comparison above covers the backend
PDF bytes; the downloaded file's filesystem location was not independently checked.
This run is not a production guarantee. Earlier native-JWT reports
keep their original dates and scope.

## Provider behavior incorporated

Verify accepts at most five authorization details per request in this tenant.
Two engine-specific globs fit that limit; exact ACLs still constrain the engine
operations and the PDF RAR names one owner and contract. Verify reorders consent
entries, so comparison checks their constraints independently of entry order.
The configured access lifetime is 120 s; independently rounded `iat` and `exp`
can differ by 121 s. The [manual](manual/17-contratacion-ciba.md) describes these
limits, the dedicated Validator requirement and the revocation API's scope.

Reproduce with `bash chatbot/scripts/verify-contracts.sh`, complete the exact
displayed approval and consent in Verify, then enable with the commands in the manual.
