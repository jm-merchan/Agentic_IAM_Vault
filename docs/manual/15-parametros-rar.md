# 15 · RAR parameters: relating rules, requests and Vault decisions

Open **Laboratorio RAR** (*RAR laboratory*) from Lumen's sidebar or from the
**Agentes por tarea** (*Task agents*) panel. It is an optional page: choosing a scenario does not change
the chat's authorization or install global restrictions. Calls are
only made when you press **Comparar peticiones reales** (*Compare real requests*).

## What is compared

Each case sends the same body to the same path with the same user and agent:

1. **Control without parameters:** OBO token with the exact path and the `update` capability.
2. **With RAR parameters:** another OBO token for that path and capability, adding
   the scenario's restrictions.

Both tokens are obtained from Verify. Lumen checks the signature, issuer, expiration,
user, actor and the exact match of `authorization_details`, including the
parameters. If Verify omits or changes a restriction, that token is not sent to
Vault. Vault evaluates the user permissions, the agent ceiling and the RAR.

The table presents real results, not a policy simulation:

| Control | With restrictions | Interpretation |
|---|---|---|
| 200 | 200 | The request was accepted with the restrictions. |
| 200 | 403 | The comparison demonstrates a denial when the RAR is added. |
| 403 | 403 | Access already fails without parameters; review the user, ceiling and blocks. Do not attribute the result to the RAR rule. |
| 200 | 200, when a denial was expected | The restriction was not enforced as expected; the discrepancy is flagged. |
| Verify, connection or engine error | Any result | Inconclusive; it is not counted as a demonstrated RAR denial. |

The control keeps the path and capability restrictions: it does not use an
administrative token or modify the ACLs. Fictitious data is encrypted; Transform creates
test tokens. The reveal scenario decrypts two synthetic profiles.
No applications or MySQL rows are modified, and the LLM is not called.

## Six scenarios

| Scenario | Restrictions | Cases | Recommended combination |
|---|---|---|---|
| Allowed encryption version | `allowed_parameters` | Version `"1"`, version `"0"`, extra `context` field and number `1` versus string `"1"`. | Writer + Creación or Estándar |
| Prohibit batches | `denied_parameters: {"batch_input": []}` | One allowed item; one denied batch. | Writer + Creación or Estándar |
| Explicit version | `required_parameters: ["key_version"]` | Present, omitted and another value present. | Writer + Creación or Estándar |
| Combination | All three fields | Compliance, `deny` on a value that is also allowed, omitted parameter and value outside the list. | Writer + Creación or Estándar |
| Explicit transformation | `required_parameters: ["transformation"]` | Name present, or inferable by the engine but omitted from the body. | Writer + Creación or Estándar |
| A single revealable profile | `allowed_parameters` on `ciphertext`, with `required_parameters` | Approved profile versus another valid ciphertext. | Supervisor + Revelado or Estándar |

The first four scenarios use `transit/encrypt/lumen-applications`; the
fifth, `transform/encode/lumen-dni`; the sixth,
`transit/decrypt/lumen-applications`. The UI shows the exact body of each
variant and the JSON of the three fields, even when one of them is not used.

`[]` has different meanings: in `allowed_parameters` it admits any
value for that field; in `denied_parameters` it prohibits the field with any value.
`required_parameters` requires presence; on its own it does not require a specific value.
In the combined scenario, the denial takes precedence over the allowed value.

The test on **Vault 2.1.2+ent** observed that the JSON number `1` did not match
the string `"1"` in the allowed list, even though Transit accepted both in the control.
Types are not normalized on the client: the UI shows the exact JSON and the
real result so that behavior changes between versions can be detected.
The restrictions act on request parameters; this lab is not presented
as an SQL row filter or as a recursive inspection of
any nested JSON object.

## Traces and request console

Each row offers **Ver control** (*View control*) and **Ver restricción** (*View restriction*). The link selects the
corresponding Vault call in the trace. Its steps keep the scenario,
case, phase, agent, HTTP status and Request ID when the server returns it.

Below the diagram, the `authorization_details` of that phase and the
synthetic body sent to Vault are shown. In the OBO exchange, the validated RAR is shown;
in the Vault call, the presented claim. This projection does not turn
decoding a JWT into validating its signature.

**Ver valores sensibles** (*View sensitive values*) and **Abrir consola de peticiones** (*Open request console*) keep the
real capture: the client's Basic credentials, subject/actor tokens, OBO JWT, headers, body and response.
The console lets you repeat that request with the captured token; it does not renew it.
The tokens may have expired by the time you repeat them. Traces can only be opened from
the session that generated them. The lab results remain while navigating
or switching ES/EN within that session; switching agents starts another session.

## Preparation and reruns

`./demo.sh start` reconciles the schema through `configure-base.sh` and prepares
the fictitious profiles during agent registration. The manual installation
includes both steps in chapters 03 and 05. To add it to an
existing installation, from the project root:

```bash
bash -c 'source scripts/demo/common.sh; load_inputs; bash chatbot/scripts/configure-rar-lab.sh'
```

The known previous schema is extended with three optional properties. The
ID, consent, description and other fields are kept. An unknown custom
schema stops the migration. OAuth clients, users, ACLs,
ceilings and the Vault version are not changed. Repeating the preparation keeps the test profiles.
It is also available as the `rar-parametros` step of the guided installer.

To load the changes into Lumen, restart only the application and its
observability tunnels; the restart closes the current sessions:

```bash
bash scripts/demo/start.sh
```

Reproducible verification with the existing fictitious users, real PKCE login,
OBO and real requests to Vault:

```bash
bash chatbot/scripts/verify-rar-parameters.sh
```

The [rar-parameters-verification.json](../../chatbot/docs/rar-parameters-verification.json) report
contains HTTP codes, the combination used and trace references, without tokens
or passwords. It includes Writer + Creación, Supervisor + Revelado,
Supervisor + Consulta and Writer + Estándar. The traces of that scripted test
are kept in the private state directory, separate from the UI sessions.

The [interface verification](../../chatbot/docs/rar-parameters-ui-verification.json)
collects tests in Chrome, the ES/EN switch, the link to the Vault step and the layout at
390 px. [Rules and results view](../screenshots/current/rar-parameters.jpg)
· [Trace view](../screenshots/current/rar-trace.jpg).

References: [RAR specification](https://developer.hashicorp.com/vault/ai/iam/reference/rar-type-specification),
[restriction enforcement](https://developer.hashicorp.com/vault/ai/iam/concepts/rar/enforcement).
