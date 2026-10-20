# 12 · Bloqueo de accesos y revocación de credenciales

[Índice](README.md) · Requiere [04](04-vault-iam.md); para xAI, [06](06-xai.md)

## 1. Entender dónde se aplica el bloqueo

`./demo.sh block ...` cambia políticas en Vault; **no modifica el RAR dentro de un JWT ya firmado**. Este capítulo muestra las operaciones CLI equivalentes. El JWT puede seguir siendo válido criptográficamente, pero Vault deniega el recurso por la política actual. JWKS no es introspection ni una lista de revocación por token.

| Bloqueo | Rutas denegadas | Credenciales ya emitidas |
|---|---|---|
| `xai` | `xai/creds/lumen`, `secrets/data/chatbot/xai-access` | Revocar leases xAI y reautorizar caché |
| `database-read` | `database/creds/chatbot-readonly` **y** `chatbot-readwrite` | Revocar ambos tipos: RW también permite SELECT |
| `database-write` | `database/creds/chatbot-readwrite` | Revocar leases RW |
| `decrypt` | Transit decrypt y Transform decode DNI/IBAN | Impedir nuevas operaciones; no borra valores ya revelados |

Los bloqueos son globales para estos agentes del laboratorio, no por usuario. No detienen necesariamente una consulta SQL o petición externa que ya esté en curso. Los efectos sobre credenciales emitidas requieren la revocación, además del deny.

## 2. Comprobar las políticas adjuntas


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
vault read -format=json agent-registry/registration/display-name/chatbot-oidc | \
  jq '.data.ceiling_policies'
# Identidad xAI, preparada junto con los otros proveedores:
vault read -format=json identity/entity/name/chatbot-xai | jq '.data.policies'
```

Esperado: `lumen-block-database-read`, `lumen-block-database-write`, `lumen-block-decrypt` en el techo OBO; `lumen-block-xai` en las políticas de la entidad autónoma xAI. Si no están adjuntas, escribir una política no tendrá efecto sobre esas identidades.

## 3. Bloquear xAI

```bash
vault policy write lumen-block-xai - <<'HCL'
path "xai/creds/lumen" { capabilities = ["deny"] }
path "secrets/data/chatbot/xai-access" { capabilities = ["deny"] }
HCL
vault lease revoke -sync -prefix xai/creds/lumen/
```

El siguiente mensaje que necesite el modelo xAI recibe denegación en Vault, incluso si había una clave en caché: Lumen verifica el marcador de autorización en cada ejecución. Si falla la revocación, mantener el deny y resolver el error/repetir la revocación; no usar `revoke-force` para simular que se retiró una clave externa.

Para desbloquear, cambiar primero la generación de caché y retirar después el deny:

```bash
openssl rand -hex 16 | jq -Rn '{generation:input}' | vault kv put -mount=secrets chatbot/xai-access -
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-xai -
```

Seleccionar **xAI** en el banner antes de probar este bloqueo. OpenAI y Claude siguen disponibles: esta política bloquea únicamente xAI, no el selector ni toda la conversación. Un token federado ya emitido continúa bajo su caducidad y controles del proveedor; el SVID no se convierte en revocable por escribir una policy xAI.

## 4. Bloquear lectura de base de datos

```bash
vault policy write lumen-block-database-read - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["deny"] }
path "database/creds/chatbot-readwrite" { capabilities = ["deny"] }
HCL
vault lease revoke -sync -prefix database/creds/chatbot-readonly/
vault lease revoke -sync -prefix database/creds/chatbot-readwrite/
```

La consulta de catálogo/solicitudes falla al pedir credenciales. Se incluyen ambos roles porque bloquear solo RO dejaría SELECT disponible a quien obtiene RW.

Desbloquear:

```bash
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-database-read -
```

## 5. Bloquear solo escritura

```bash
vault policy write lumen-block-database-write - <<'HCL'
path "database/creds/chatbot-readwrite" { capabilities = ["deny"] }
HCL
vault lease revoke -sync -prefix database/creds/chatbot-readwrite/
```

El gestor puede consultar por RO, pero falla al guardar. Su capacidad de cifrar/tokenizar permanece; la combinación necesaria para guardar ya no está completa.

Desbloquear:

```bash
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-database-write -
```

## 6. Bloquear recuperación de datos sensibles

```bash
vault policy write lumen-block-decrypt - <<'HCL'
path "transit/decrypt/lumen-applications" { capabilities = ["deny"] }
path "transform/decode/lumen-dni" { capabilities = ["deny"] }
path "transform/decode/lumen-iban" { capabilities = ["deny"] }
HCL
```

El supervisor sigue leyendo versiones enmascaradas, pero una nueva operación de revelado devuelve 403. No existen leases de descifrado que revocar; un dato ya mostrado en pantalla no se puede retirar retroactivamente.

Desbloquear:

```bash
printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write lumen-block-decrypt -
```

## 7. Demostrar el efecto sobre un JWT anterior

En [11](11-obo.md), obtener un JWT OBO válido para RO y conservarlo en `obo.json`. Sin pedir otro JWT, activar `lumen-block-database-read` y repetir:

```bash
if VAULT_TOKEN=$(jq -er .access_token "$MANUAL/obo.json") \
  vault read -format=json database/creds/chatbot-readonly \
  > "$MANUAL/blocked.json" 2> "$MANUAL/blocked.log"; then
  printf 'ERROR: se esperaba bloqueo\n' >&2
  exit 1
fi
cat "$MANUAL/blocked.log"
```

Comprobar 403. Quitar el deny y repetir mientras el JWT siga vigente: debe volver a permitir esa ruta si el usuario y RAR la permiten. Un JWT nuevo con el mismo RAR también queda denegado durante el bloqueo.

La ausencia de bloqueo adicional no concede permisos: el lector continúa sin RW y el gestor sin decrypt. Cambiar `authorization_details` al solicitar un token nuevo reduce su alcance, pero no elimina tokens anteriores. Para hacer un JWT de un uso habría que añadir un control de consumo/replay distinto; no es lo configurado aquí.

Fuentes locales: [block.sh](../../scripts/demo/block.sh), [access-controls.sh](../../chatbot/scripts/access-controls.sh), [explicación de los controles](../ACCESS_BLOCKS.md).

Los bloqueos de Database y de descifrado afectan a las herramientas OBO con cualquiera de los tres modelos. Cambiar el proveedor no cambia los permisos del usuario, las políticas de Vault ni los límites del agente.
