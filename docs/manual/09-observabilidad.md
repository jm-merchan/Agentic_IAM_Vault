# 09 · Audit log de Vault y trazas en Grafana

[Índice](README.md) · Requiere [01](01-vault.md) · Continuar con [Arranque](10-aplicacion.md)

## 1. Habilitar auditoría en el namespace root

Puede hacerse después de inicializar Vault, antes de configurar el resto, si se quiere auditar también el aprovisionamiento. No recupera retroactivamente llamadas anteriores.


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
export VAULT_NAMESPACE=''
vault audit list -format=json
vault audit enable -path=lumen-stdout file file_path=stdout log_raw=false hmac_accessor=true
vault write sys/config/auditing/request-headers/traceparent hmac=false
```

En un Vault recién inicializado, `vault audit list` en formato tabla devuelve código 2 si no hay dispositivos y detendría una sesión con `set -e`. La variante JSON devuelve `{}` y permite continuar.

Si `lumen-stdout/` ya existe, conservarlo y su salt HMAC; no deshabilitarlo para recrearlo. El dispositivo general protege valores. Los siguientes dispositivos adicionales guardan datos raw exclusivamente en las rutas de la demo, reproduciendo el modo de laboratorio solicitado.

## 2. Añadir dispositivos raw filtrados

Estos logs incluyen JWT, credenciales emitidas y respuestas de protección de datos en claro; se almacenan en el laboratorio local junto a las trazas. Es una configuración deliberada de observabilidad, no una propiedad necesaria de Agentic IAM.

```bash
AGENT_FILTER='namespace == "verify/" and operation == "read" and (path == "database/creds/chatbot-readonly" or path == "database/creds/chatbot-readwrite" or path == "secrets/data/tavily" or path == "secrets/data/verify-admin")'
PROTECTION_FILTER='namespace == "verify/" and (path == "transit/encrypt/lumen-applications" or path == "transit/decrypt/lumen-applications" or path == "transform/encode/lumen-dni" or path == "transform/decode/lumen-dni" or path == "transform/encode/lumen-iban" or path == "transform/decode/lumen-iban")'
XAI_FILTER='namespace == "verify/" and path == "xai/creds/lumen"'
XAI_ACCESS_FILTER='namespace == "verify/" and path == "secrets/data/chatbot/xai-access"'
SPIFFE_FILTER='namespace == "verify/" and (path == "spiffe/role/lumen-openai/mintjwt" or path == "spiffe/role/lumen-anthropic/mintjwt")'
```

```bash
vault audit enable -path=lumen-agent-raw file \
  file_path=/dev/stdout mode=0000 log_raw=true hmac_accessor=false filter="$AGENT_FILTER"
vault audit enable -path=lumen-protection-raw file \
  file_path=/dev/stderr mode=0000 log_raw=true hmac_accessor=false filter="$PROTECTION_FILTER"
vault audit enable -path=lumen-xai-raw file \
  file_path=/proc/self/fd/1 mode=0000 log_raw=true hmac_accessor=false filter="$XAI_FILTER"
vault audit enable -path=lumen-xai-access-raw file \
  file_path=/dev/fd/1 mode=0000 log_raw=true hmac_accessor=false filter="$XAI_ACCESS_FILTER"
vault audit enable -path=lumen-spiffe-raw file \
  file_path=/proc/self/fd/2 mode=0000 log_raw=true hmac_accessor=false filter="$SPIFFE_FILTER"
vault audit list -format=json | jq 'with_entries(.value |= {type,options})'
```

Omitir los `enable` de dispositivos ya existentes y comparar sus opciones. Los distintos paths de stdout/stderr permiten identificar dispositivos separados. Un mismo request puede aparecer en HMAC y en raw: contar IDs de petición únicos, no líneas.

## 3. Preparar ConfigMaps y la contraseña Grafana

[stack.yaml](../../chatbot/observability/stack.yaml) despliega Grafana, Tempo, Loki y Alloy, con volúmenes persistentes y servicios internos. Alloy tiene un Role/RoleBinding en `vault` para leer pods y logs; su ServiceAccount vive en `lumen-observability`.

```bash
export VAULT_NAMESPACE=verify
"${K[@]}" create namespace lumen-observability --dry-run=client -o yaml | "${K[@]}" apply -f -
for item in 'loki-config:loki.yaml' 'tempo-config:tempo.yaml' 'alloy-config:config.alloy' \
  'grafana-datasources:datasources.yaml' 'grafana-providers:dashboards.yaml' 'grafana-dashboards:dashboard.json'; do
  name=${item%%:*}; file=${item#*:}
  "${K[@]}" -n lumen-observability create configmap "$name" \
    --from-file="$file=chatbot/observability/$file" --dry-run=client -o yaml | "${K[@]}" apply -f -
done
```

Solo si no existe `secrets/chatbot/observability`, generar la credencial:

```bash
openssl rand -hex 24 | tr -d '\n' > "$MANUAL/grafana-password"
jq -n --rawfile password "$MANUAL/grafana-password" \
  '{username:"lumen-admin",password:$password,url:"http://localhost:3000"}' | \
  vault kv put -mount=secrets chatbot/observability -
```

Leerla desde Vault y usarla como Secret Kubernetes. En una Grafana ya inicializada, cambiar el Secret no rota automáticamente su contraseña persistida; conservar la credencial existente.

```bash
vault kv get -format=json -mount=secrets chatbot/observability | \
  jq -jr .data.data.password > "$MANUAL/grafana-password"
"${K[@]}" -n lumen-observability create secret generic grafana-admin \
  --from-file="password=$MANUAL/grafana-password" --dry-run=client -o json | "${K[@]}" apply -f -
rm -- "$MANUAL/grafana-password"
"${K[@]}" apply -f chatbot/observability/stack.yaml
for name in grafana tempo loki alloy; do
  "${K[@]}" -n lumen-observability rollout status "deployment/$name" --timeout=240s
done
```

Versiones fijadas en el manifiesto: Grafana 13.2.4, Loki 3.7.8, Tempo 2.10.8 y Alloy **v1.21.0-rc.0**. Alloy es una versión candidata elegida por la corrección de pérdida de eventos al intercalar timestamps; no se presenta como una versión estable. [Incidencia y validación de esta demo](../E2E_OPENAI_VERIFICATION.md).

## 4. Abrir los puertos locales

Cada comando ocupa su propia terminal; mantenerlas abiertas. No duplicar un forward existente:

```bash
kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/grafana 3000:3000
```

```bash
kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 4318:4318 3200:3200
```

```bash
kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/loki 3100:3100
```

Comprobar salud desde la terminal principal:

```bash
curl --fail --silent --show-error http://127.0.0.1:3000/api/health
curl --fail --silent --show-error http://127.0.0.1:3200/ready
curl --fail --silent --show-error http://127.0.0.1:3100/ready
```

## 5. Acceder y correlacionar peticiones

Grafana: [dashboard Lumen](http://localhost:3000/d/lumen-iam), usuario `lumen-admin`. En macOS copiar su contraseña sin imprimirla:

```bash
vault kv get -format=json -mount=secrets chatbot/observability | jq -jr .data.data.password | pbcopy
```

La app exporta OTLP a `http://127.0.0.1:4318/v1/traces`; Alloy recoge los audit logs de Vault y los manda a Loki. La cabecera W3C `traceparent` une ambos. El detalle `vault.request_id` permite identificar el par request/response; las llamadas hechas con Vault CLI producen audit logs pero **no crean spans de Lumen automáticamente**.

Después de una acción UI, abrir **Ver última traza → Ver en Grafana** (**View latest trace → View in Grafana** en inglés). El visor de Lumen muestra primero el diagrama de llamadas, con iconos de los servicios, filtro de destino y detalles al seleccionar una flecha. **EN / ES** cambia títulos, explicaciones y paginación; los nombres técnicos y valores capturados se conservan. En laboratorio, **Ver valores sensibles / View sensitive values** abre OAuth/HTTP Basic, SVID, credenciales dinámicas y cuerpos de la operación correspondiente. [Alcance y retención del visor](../../chatbot/OBSERVABILITY.md#valores-de-cada-llamada) · [Comprobar idiomas](10-aplicacion.md#idioma-y-comprobaciones-bilingües).

También se puede consultar con el Trace ID real de esa acción:

```bash
read -r -p 'Trace ID (32 caracteres hex): ' TRACE_ID
[[ "$TRACE_ID" =~ ^[0-9a-f]{32}$ ]]
curl --fail --silent --show-error "http://127.0.0.1:3200/api/traces/$TRACE_ID" \
  > "$MANUAL/trace.json"
LOKI_QUERY="{service=\"vault-audit\"} |= \"$TRACE_ID\""
curl --fail --silent --show-error --get http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode "query=$LOKI_QUERY" --data-urlencode 'since=1h' --data-urlencode 'limit=500' \
  > "$MANUAL/audit-trace.json"
jq '[.data.result[].values[]]|length' "$MANUAL/audit-trace.json"
```

En Loki Explore, usar `{service="vault-audit",audit_mode="raw"}` y filtrar por Trace ID o `request.id`. En Tempo se ven modelo, prompts/respuestas, herramientas, OBO y llamadas Vault. Los JSON completos pueden contener secretos del laboratorio: conservarlos en `$MANUAL`.

Campos explícitos del SVID en modo raw: `spiffe.jwt_svid`, `spiffe.jwt_svid.decoded`, `openai.exchange.subject_token`. Los JWT de acceso a Vault aparecen en `vault.auth.jwt`; petición y respuesta completas, en `vault.http.request` / `vault.http.response`. El visor también muestra `guardrail.energy_scope`. [Contenido y alcance del traceo](../ENERGY_SCOPE_AND_SVID.md).

Fuentes locales: [enable-audit.sh](../../chatbot/scripts/enable-audit.sh), [config.alloy](../../chatbot/observability/config.alloy), [datasources.yaml](../../chatbot/observability/datasources.yaml), [dashboard.json](../../chatbot/observability/dashboard.json).

## Actualizar el filtro SPIFFE de una instalación existente

El filtro raw anterior solo incluía OpenAI. Para correlacionar también Claude, actualizar únicamente el dispositivo dedicado a SPIFFE; conservar el audit general activo. No es necesario para cambiar de proveedor desde el banner si el filtro ya incluye ambos roles.

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=''
SPIFFE_FILTER='namespace == "verify/" and (path == "spiffe/role/lumen-openai/mintjwt" or path == "spiffe/role/lumen-anthropic/mintjwt")'
vault audit list -format=json > "$MANUAL/audit-spiffe.json"
jq -e 'has("lumen-stdout/")' "$MANUAL/audit-spiffe.json" >/dev/null
if jq -e --arg filter "$SPIFFE_FILTER" 'has("lumen-spiffe-raw/") and .["lumen-spiffe-raw/"].options.filter!=$filter' "$MANUAL/audit-spiffe.json" >/dev/null; then
  vault audit disable lumen-spiffe-raw
fi
if ! vault audit list -format=json | jq -e 'has("lumen-spiffe-raw/")' >/dev/null; then
  vault audit enable -path=lumen-spiffe-raw file \
    file_path=/proc/self/fd/2 mode=0000 log_raw=true hmac_accessor=false filter="$SPIFFE_FILTER"
fi
vault audit list -format=json | jq -e --arg filter "$SPIFFE_FILTER" \
  '.["lumen-spiffe-raw/"].options.filter==$filter'
export VAULT_NAMESPACE=verify
```
