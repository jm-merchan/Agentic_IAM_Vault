#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD_DIR=$(mktemp -d /tmp/lumen-protection-notebook.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT
printf '[]' > "$BUILD_DIR/cells.json"
add_cell() {
  local kind=$1
  cat > "$BUILD_DIR/source"
  jq --arg kind "$kind" --rawfile source "$BUILD_DIR/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$BUILD_DIR/cells.json" > "$BUILD_DIR/next"
  mv "$BUILD_DIR/next" "$BUILD_DIR/cells.json"
}
add_cell markdown <<'MD'
# Lumen — solicitudes protegidas con tres perfiles

Referencia de solicitudes protegidas; `./demo.sh` incluye estas etapas. Formulario en cinco pasos, OBO, Transit y Transform tokenization; mantiene MySQL KMIP. Aprovisionamiento **Bash + Vault CLI + API Verify**, sin Terraform ni Python para configurar los proveedores. La aplicación continúa en NiceGUI/Python con Deep Agents y selección OpenAI/xAI/Claude.

Ejecutar desde la raíz del repositorio. Los notebooks 1–6 deben estar preparados; la observabilidad del 7 permite ver las trazas de esta extensión. Este notebook se entrega sin salidas ni credenciales.

[README con recorrido y capturas](chatbot/README.md#solicitudes-en-cinco-pasos) · [Observabilidad](chatbot/OBSERVABILITY.md#9-solicitudes-protegidas-transit-y-transform)
MD
add_cell markdown <<'MD'
## 1. Comprobar Vault, licencia y MySQL

Namespace Vault **verify**, contexto Kubernetes **workshop**. La licencia debe incluir Transform Secrets Engine y Agentic IAM. El proyecto `Demo_Transform_Radar` sirve como referencia para Transit/Transform; sus datos y claves no se copian.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
source /tmp/vault/config.env
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT VAULT_NAMESPACE=''
vault read -format=json sys/license/status | jq '.data.autoloaded | {expiration_time,features}'
export VAULT_NAMESPACE=verify
vault secrets list
kubectl --context workshop -n mysql get pod mysql-enterprise-0
CODE
add_cell markdown <<'MD'
## 2. Crear protección y tabla adicional

Crea `transit/keys/lumen-applications` (AES-256-GCM, no exportable), transformaciones de tokenización `lumen-dni` y `lumen-iban` con roles del mismo nombre, `convergence=false` y `mapping_mode=default`. Reutiliza recursos existentes. Crea `scripting.energy_applications` con InnoDB `ENCRYPTION='Y'`, sin borrar ni alterar las solicitudes antiguas.

Nombre, domicilio, contacto y nota se guardan en un JSON cifrado. DNI e IBAN se guardan como tokens aleatorios. Tarifa, identidad de sesión, estado, fecha y pistas enmascaradas son metadatos en claro. El cifrado KMIP del tablespace sigue siendo otra capa independiente.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/06-data-protection.sh
CODE
add_cell markdown <<'MD'
## 3. Tres perfiles y políticas OBO

| Usuario | Grupo Verify | SQL | Protección |
|---|---|---|---|
| lumen-reader | chatbot-readers | RO | Solo pistas enmascaradas |
| lumen-writer (gestor) | chatbot-writers | RW | Encrypt + encode |
| lumen-supervisor | chatbot-supervisors | RO | Decrypt + decode |

El script 03 crea/activa el supervisor mediante los permisos administrativos ya existentes y conserva las contraseñas de usuarios existentes. Las tres contraseñas están en `verify`, KV `secrets`, rutas `chatbot/users/{reader,writer,supervisor}`. No imprimirlas en celdas.

04 limita el agente a ocho rutas: dos credenciales DB y seis operaciones criptográficas. 05 sincroniza miembros, entidades, políticas y asignación a OIDC. RAR usa **read** para credenciales y **update** para operaciones criptográficas. Reiniciar Lumen después.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/03-verify-users.sh
bash chatbot/scripts/04-vault-agents.sh
bash chatbot/scripts/05-sync-groups.sh
CODE
add_cell code <<'CODE'
%%bash
set -euo pipefail
source /tmp/vault/config.env
export VAULT_ADDR VAULT_TOKEN VAULT_CACERT VAULT_NAMESPACE=verify
for policy in chatbot-reader chatbot-writer chatbot-supervisor chatbot-data-ceiling; do
  printf '\nPolicy: %s\n' "$policy"
  vault policy read "$policy"
done
CODE
add_cell markdown <<'MD'
## 4. Auditoría y trazas

Se conserva HMAC en `lumen-stdout/`. Las salidas raw filtran las cuatro rutas de lectura de la demo y las seis rutas Transit/Transform en `verify/`. `lumen-protection-raw/` no filtra operación, para conservar también los eventos request de denegaciones. Las rutas son exactas, sin comodines. La salida `lumen-xai-raw/` cubre además `xai/creds/lumen`.

**En este laboratorio el usuario pidió raw:** las trazas y auditorías incluyen JWT, cuerpos de petición y respuesta; también DNI/IBAN en claro y JSON Base64 antes de cifrar. No equivale a confidencialidad frente a los operadores de observabilidad. Utilizar el botón de datos ficticios.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
LUMEN_VAULT_AUDIT_MODE=raw bash chatbot/scripts/enable-audit.sh
CODE
add_cell markdown <<'MD'
## 5. Arrancar o reiniciar Lumen

Detener la instancia anterior antes de ejecutar esta celda. Permanece ejecutándose. Abrir exactamente **http://localhost:8088** por el callback OIDC.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
LUMEN_TRACE_VAULT_RAW=1 bash chatbot/scripts/run.sh
CODE
add_cell markdown <<'MD'
## 6. Recorrido interactivo

Las etiquetas siguientes están en español: selecciona **ES** para seguirlas literalmente. **EN** cambia el formulario, validaciones y bandeja a inglés; el idioma inicial procede del navegador si no hay elección guardada. **Take the next step**, **Use test data**, **Save application** y **Reveal data** son las equivalencias de **Da el siguiente paso**, **Usar datos de prueba**, **Guardar solicitud** y **Revelar datos**. Cambiar EN/ES mantiene el paso y los datos escritos durante la sesión, con los mismos permisos y validaciones de DNI/IBAN españoles. [Prueba de conservación sin guardar una solicitud](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües).

1. **Gestor**: entrar con `lumen-writer`. «Da el siguiente paso» → aceptar sugerencias aleatorias con Tab (o «Usar datos de prueba») → recorrer tarifa, vivienda, titular, pago y revisión. Probar una letra incorrecta del DNI o modificar los dígitos de control del IBAN: el avance queda bloqueado. Revisar, marcar confirmación y guardar.
2. **Gestor**: en «Solicitudes», pulsar «Revelar datos». Se lee ciphertext con SQL RW, pero Vault deniega Transit decrypt con HTTP 403. Abrir el enlace de traza del diálogo.
3. **Lector**: cambiar de usuario desde el chat a `lumen-reader`. La bandeja muestra pistas; revelar produce también 403. Crear solicitudes queda bloqueado. «Comprobar límites en Vault» deniega credencial RW.
4. **Supervisor**: entrar como `lumen-supervisor` y aceptar el consentimiento OIDC normal de primer acceso. Revelar la misma solicitud: SQL RO → Transit decrypt → Transform decode DNI → Transform decode IBAN. «Ocultar y cerrar» elimina el diálogo. Crear solicitudes y obtener RW siguen bloqueados.
5. **Chat/LLM**: «Consulta las solicitudes registradas». La herramienta devuelve la proyección enmascarada; el formulario y los datos revelados no se añaden al prompt. Tavily mantiene su agente autónomo separado.

![Revisión](docs/runs/20261014T162141Z/screenshots/17-form-review.jpg)
![Gestor denegado](docs/runs/20261014T162141Z/screenshots/19-writer-reveal-denied.jpg)
![Supervisor autorizado](docs/runs/20261014T162141Z/screenshots/27-supervisor-reveal.jpg)

La bandeja es compartida **solo para este laboratorio**. SQL RO no aplica seguridad por fila ni columna: puede leer ciphertext/tokens, pero Vault exige políticas independientes para revelarlos.
MD
add_cell markdown <<'MD'
## 7. Comprobar almacenamiento sin imprimir datos en claro

Los indicadores deben ser `1` para las solicitudes creadas por el formulario, también con las sugerencias aleatorias. No se compara contra antiguos valores de ejemplo fijos. Esta comprobación administrativa se realiza directamente en MySQL, fuera del flujo del agente. No descifra ni destokeniza.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
kubectl --context workshop -n mysql exec -i mysql-enterprise-0 -c mysql -- \
 sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4' <<'SQL'
SELECT application_id,
 profile_ciphertext LIKE 'vault:v1:%' AS transit_ciphertext,
 dni_token NOT REGEXP '^[0-9]{8}[A-Z]$' AS dni_token_is_opaque,
 iban_token NOT REGEXP '^ES[0-9]{22}$' AS iban_token_is_opaque,
 (SELECT ENCRYPTION='Y' FROM information_schema.innodb_tablespaces
   WHERE NAME='scripting/energy_applications') AS table_encrypted,
 dni_hint,iban_hint
FROM scripting.energy_applications;
SQL
CODE
add_cell markdown <<'MD'
## 8. Pruebas y correlación

Las pruebas unitarias cubren normalización y checksum, bloqueo del perfil RO en servidor, protección antes de INSERT, fallo sin fila parcial, reintento sin duplicación, recuperación denegada y captura POST. Los informes JSON de pruebas reales solo guardan identificadores, tamaños y booleanos.
MD
add_cell code <<'CODE'
%%bash
set -euo pipefail
cd chatbot
/tmp/vault-chatbot-venv/bin/python -m pytest -q tests
for report in docs/application-save-verification.json docs/application-reveal-verification.json docs/application-denials-verification.json; do
  jq '{checked_at,all_passed,traces:[.traces[]|{trace_id,span_count,raw_capture_checks}]}' "$report"
done
CODE
add_cell code <<'CODE'
%%bash
set -euo pipefail
# Sustituir por el ID de una nueva ejecución; los datos de Tempo/Loki retienen 7 días.
TRACE_ID=''
if [ -z "$TRACE_ID" ]; then
  echo 'Copia el Trace ID del enlace de guardado/revelación y repite esta celda.'
else
  LUMEN_OBSERVABILITY_REPORT=chatbot/docs/application-latest-verification.json \
    bash chatbot/scripts/verify-observability.sh "$TRACE_ID"
fi
CODE
add_cell markdown <<'MD'
## 9. Repetición y límites

Los scripts reutilizan usuarios, motores, roles y claves. No hay limpieza destructiva ni migración de `service_requests`; los borradores originales siguen en «Borradores anteriores». Una fila nueva solo se inserta después de obtener los tres resultados protegidos. Un fallo posterior a tokenizar puede dejar asociaciones de token sin fila SQL, pues no hay transacción distribuida entre Vault y MySQL.

Para nuevas ejecuciones sin contenido raw: `LUMEN_VAULT_AUDIT_MODE=hmac bash chatbot/scripts/enable-audit.sh`, detener Lumen y arrancar con `LUMEN_TRACE_CONTENT=0 LUMEN_TRACE_VAULT_RAW=0 bash chatbot/scripts/run.sh`. Esto no elimina registros previos.

Referencias: [Transit](https://developer.hashicorp.com/vault/api-docs/secret/transit), [Transform](https://developer.hashicorp.com/vault/api-docs/secret/transform), [tokenización](https://developer.hashicorp.com/vault/docs/secrets/transform/tokenization), [OBO](https://developer.hashicorp.com/vault/ai/iam/setup-obo).
MD
jq -n --slurpfile cells "$BUILD_DIR/cells.json" '{nbformat:4,nbformat_minor:5,metadata:{kernelspec:{display_name:"Python 3 (IPython Bash magics)",language:"python",name:"python3"},language_info:{name:"python"}},cells:$cells[0]}' > 8_Lumen_Protected_Applications.ipynb
printf 'Notebook 8 generated.\n'
