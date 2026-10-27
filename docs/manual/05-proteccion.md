# 05 · Transit and Transform for protected applications

[Index](README.md) · Requires [02](02-mysql.md) and [04](04-vault-iam.md)

## 1. Create the engines and the Transit key


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
vault secrets list
```

Skip each `enable` if the engine is already mounted. In a new installation:

```bash
vault secrets enable transit
vault secrets enable transform
vault write transit/keys/lumen-applications type=aes256-gcm96 \
  exportable=false allow_plaintext_backup=false
for field in dni iban; do
  vault write "transform/transformations/tokenization/lumen-$field" \
    allowed_roles="lumen-$field" convergence=false mapping_mode=default
  vault write "transform/role/lumen-$field" transformations="lumen-$field"
done
vault read transit/keys/lumen-applications
vault read transform/role/lumen-dni
vault read transform/role/lumen-iban
```

Transit encrypts the complete profile with AES-GCM; Transform tokenizes the DNI and IBAN. Tokenization with mappings is used, **not FPE**: the token does not need to keep the DNI/IBAN format. `convergence=false` allows different tokens for the same value. KMIP protects the tablespaces and is an independent layer.

## 2. Create the applications table


```bash
"${K[@]}" -n mysql exec -i mysql-enterprise-0 -c mysql -- \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4' <<'SQL'
CREATE TABLE IF NOT EXISTS scripting.energy_applications (
  application_id CHAR(36) PRIMARY KEY,
  subject_id VARCHAR(120) NOT NULL,
  plan_id INT NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'recibida',
  profile_ciphertext TEXT NOT NULL,
  dni_token TEXT NOT NULL,
  iban_token TEXT NOT NULL,
  dni_hint VARCHAR(40) NOT NULL,
  iban_hint VARCHAR(80) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (plan_id) REFERENCES scripting.energy_plans(id)
) ENGINE=InnoDB ENCRYPTION='Y';
SQL
```

`profile_ciphertext`, `dni_token` and `iban_token` contain the Vault outputs. `dni_hint` and `iban_hint` are masked versions; tariff, status and reference remain readable. The five-step flow is implemented by [applications.py](../../chatbot/app/applications.py), with a stable UUID to avoid duplicating the application on retry.

## 3. Prepare synthetic values for the permissions button

This block configures the runtime's test inputs. It uses root to prepare them, but **the app's button accesses Vault again with OBO** and can therefore receive a 403.

```bash
jq -n '{version:1,profile_plaintext:("lumen-permission-probe"|@base64),
  dni:{value:"lumen-probe-dni"},iban:{value:"lumen-probe-iban"}}' > "$MANUAL/probe.json"
jq '{plaintext:.profile_plaintext}' "$MANUAL/probe.json" | \
  vault write -format=json transit/encrypt/lumen-applications - > "$MANUAL/encrypted.json"
jq --slurpfile result "$MANUAL/encrypted.json" '.profile_ciphertext=$result[0].data.ciphertext' \
  "$MANUAL/probe.json" > "$MANUAL/next.json"
mv "$MANUAL/next.json" "$MANUAL/probe.json"
for field in dni iban; do
  jq --arg field "$field" '{value:.[$field].value,transformation:("lumen-"+$field)}' \
    "$MANUAL/probe.json" | vault write -format=json "transform/encode/lumen-$field" - \
    > "$MANUAL/encoded.json"
  jq --arg field "$field" --slurpfile result "$MANUAL/encoded.json" \
    '.[$field].token=$result[0].data.encoded_value' "$MANUAL/probe.json" > "$MANUAL/next.json"
  mv "$MANUAL/next.json" "$MANUAL/probe.json"
done
vault kv get -format=json -mount=secrets chatbot/runtime | jq '.data.data' > "$MANUAL/runtime.json"
jq --slurpfile probe "$MANUAL/probe.json" '.permission_probe=$probe[0]' "$MANUAL/runtime.json" | \
  vault kv put -mount=secrets chatbot/runtime -
bash chatbot/scripts/configure-rar-fixtures.sh
```

## 4. Understand the recovery operations

Administrative round-trip test; the result is saved locally:

```bash
jq '{ciphertext:.profile_ciphertext}' "$MANUAL/probe.json" | \
  vault write -format=json transit/decrypt/lumen-applications - > "$MANUAL/decrypted.json"
jq -e --slurpfile probe "$MANUAL/probe.json" \
  '.data.plaintext==$probe[0].profile_plaintext' "$MANUAL/decrypted.json"
jq '{value:.dni.token,transformation:"lumen-dni"}' "$MANUAL/probe.json" | \
  vault write -format=json transform/decode/lumen-dni - > "$MANUAL/decoded.json"
jq -e --slurpfile probe "$MANUAL/probe.json" '.data.decoded_value==$probe[0].dni.value' "$MANUAL/decoded.json"
```

To demonstrate authorization, repeat these operations with an OBO JWT that includes RAR for that path and `capabilities:["update"]`, as explained in [11](11-obo.md). With root they would always be allowed.

| Operation | Reader | Writer | Supervisor |
|---|---|---|---|
| Read masked applications (SQL RO) | Yes | Yes | Yes |
| Save an application (SQL RW + encrypt/encode) | No | Yes | No |
| Reveal profile, DNI and IBAN (decrypt/decode) | No | No | Yes |

Permission to create an application requires all of its operations to work. The personal data in the form is not sent to the LLM. [Validation of the manual installation](VALIDACION.md).

Local sources: [06-data-protection.sh](../../chatbot/scripts/06-data-protection.sh), [configure-permission-probe.sh](../../chatbot/scripts/configure-permission-probe.sh).
