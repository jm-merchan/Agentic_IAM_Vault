# 05 · Transit y Transform para solicitudes protegidas

[Índice](README.md) · Requiere [02](02-mysql.md) y [04](04-vault-iam.md)

## 1. Crear los motores y la clave Transit


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
vault secrets list
```

Omitir cada `enable` si el motor ya está montado. En una instalación nueva:

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

Transit cifra el perfil completo con AES-GCM; Transform tokeniza DNI e IBAN. Se usa tokenización con mappings, **no FPE**: el token no tiene por qué conservar formato DNI/IBAN. `convergence=false` permite tokens diferentes para el mismo valor. KMIP protege los tablespaces y es una capa independiente.

## 2. Crear la tabla de solicitudes


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

`profile_ciphertext`, `dni_token` e `iban_token` contienen las salidas de Vault. `dni_hint` e `iban_hint` son versiones enmascaradas; tarifa, estado y referencia permanecen legibles. El flujo de cinco pasos lo implementa [applications.py](../../chatbot/app/applications.py), con un UUID estable para evitar duplicar la solicitud al reintentar.

## 3. Preparar valores sintéticos para el botón de permisos

Este bloque configura las entradas de prueba del runtime. Usa root para prepararlas, pero **el botón de la app vuelve a acceder con OBO** y, por tanto, puede recibir 403.

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

## 4. Entender las operaciones de recuperación

Prueba administrativa de ida y vuelta; el resultado se guarda localmente:

```bash
jq '{ciphertext:.profile_ciphertext}' "$MANUAL/probe.json" | \
  vault write -format=json transit/decrypt/lumen-applications - > "$MANUAL/decrypted.json"
jq -e --slurpfile probe "$MANUAL/probe.json" \
  '.data.plaintext==$probe[0].profile_plaintext' "$MANUAL/decrypted.json"
jq '{value:.dni.token,transformation:"lumen-dni"}' "$MANUAL/probe.json" | \
  vault write -format=json transform/decode/lumen-dni - > "$MANUAL/decoded.json"
jq -e --slurpfile probe "$MANUAL/probe.json" '.data.decoded_value==$probe[0].dni.value' "$MANUAL/decoded.json"
```

Para demostrar autorización, repetir estas operaciones con un JWT OBO que incluya RAR para esa ruta y `capabilities:["update"]`, como explica [11](11-obo.md). Con root siempre serían permitidas.

| Operación | Lector | Gestor | Supervisor |
|---|---|---|---|
| Leer solicitudes enmascaradas (SQL RO) | Sí | Sí | Sí |
| Guardar solicitud (SQL RW + encrypt/encode) | No | Sí | No |
| Revelar perfil, DNI e IBAN (decrypt/decode) | No | No | Sí |

El permiso de crear una solicitud requiere que funcionen todas sus operaciones. Los datos personales del formulario no se envían al LLM. [Validación de la instalación manual](VALIDACION.md).

Fuentes locales: [06-data-protection.sh](../../chatbot/scripts/06-data-protection.sh), [configure-permission-probe.sh](../../chatbot/scripts/configure-permission-probe.sh).
