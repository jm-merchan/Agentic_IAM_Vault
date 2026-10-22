#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
BUILD_DIR=$(mktemp -d /tmp/lumen-observability-notebook.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT
printf '[]' > "$BUILD_DIR/cells.json"
cell() {
  local kind=$1
  cat > "$BUILD_DIR/source"
  jq --arg kind "$kind" --rawfile source "$BUILD_DIR/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($source|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$BUILD_DIR/cells.json" > "$BUILD_DIR/next"
  mv "$BUILD_DIR/next" "$BUILD_DIR/cells.json"
}
cell markdown <<'MD'
# Lumen — permisos, audit log de Vault y trazas del agente

Referencia de observabilidad; `./demo.sh` incluye estas etapas. Aprovisionamiento **Bash**, contexto Kubernetes `workshop`, namespace `lumen-observability`. Grafana 13.2.4 + Loki 3.7.8 + Tempo 2.10.8 (modo monolítico) + Alloy 1.21.0-rc.0. Se fija esta versión candidata para el laboratorio porque incorpora la corrección de pérdida de líneas stdout/stderr [grafana/alloy#7080](https://github.com/grafana/alloy/pull/7080). Aplicación instrumentada con OpenTelemetry 1.45.1. Servicios ClusterIP; accesos del navegador y OTLP mediante port-forward en `127.0.0.1`. No se publica un Ingress ni NodePort. [Revisión vigente de interfaz y servicios](docs/runs/20261022T140230Z-workspace-review/README.md).

[Guía del recorrido con capturas](chatbot/OBSERVABILITY.md) · [Verificación ejecutada](chatbot/docs/observability-verification.json)

Vault no tenía auditoría habilitada al empezar esta ampliación. Solo hay evidencia desde su activación; no reconstruye peticiones anteriores. La configuración actual conserva `lumen-stdout/` con HMAC y añade `lumen-agent-raw/`, filtrado a cuatro rutas de lectura, y `lumen-protection-raw/`, filtrado a seis rutas Transit/Transform en `verify`, sin HMAC; `lumen-xai-raw/` cubre `xai/creds/lumen`. Los JWT, cuerpos y respuestas completos también aparecen en `vault.read` y `vault.write` (notebook 8).
MD
cell markdown <<'MD'
## 1. Activar auditoría y correlación

Seis dispositivos raíz: `lumen-stdout/` protegido y cinco salidas raw (`lumen-agent-raw/`, `lumen-protection-raw/`, `lumen-xai-raw/`, `lumen-xai-access-raw/`, `lumen-spiffe-raw/`) con filtros distintos. `traceparent` une las copias con Tempo. No cambia políticas de usuarios ni del agente. Alloy lee logs de los tres pods de Vault por API de Kubernetes, con RBAC de lectura restringido al namespace `vault`; etiqueta las copias como `audit_mode=raw` o `hmac`.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/enable-audit.sh
CODE
cell markdown <<'MD'
## 2. Desplegar Grafana, Loki, Tempo y Alloy

PVCs: Loki 5 GiB, Tempo 5 GiB, Grafana 1 GiB. Retención de logs/trazas: 7 días; almacenamiento local de laboratorio, sin HA. Admin de Grafana: `lumen-admin`; contraseña aleatoria guardada en Vault `verify/secrets/chatbot/observability` y en el Secret Kubernetes `lumen-observability/grafana-admin`. El chatbot no puede leer ese secreto. El script reutiliza la credencial existente. Grafana tiene un límite de 1536 MiB y `GOMEMLIMIT=768MiB`. En el arranque con `demo.sh`, `launchd` recupera los port-forward cuando se interrumpe su conexión.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/deploy-observability.sh
for deployment in grafana loki tempo alloy; do
  kubectl --context workshop -n lumen-observability rollout status deployment/$deployment --timeout=180s
done
CODE
cell markdown <<'MD'
## 3. Abrir puertos locales e iniciar la aplicación instrumentada

Para el despliegue completo desde la raíz:

```bash
./demo.sh
```

El lanzador mantiene port-forwards y aplicación mediante servicios de usuario. Los scripts individuales son para mantenimiento; no hacen falta terminales adicionales. La configuración se lee de `.env`.

`run.sh` usa `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces`. Los tokens de bootstrap siguen siendo temporales y limitados. El proveedor se elige en el banner entre los perfiles OpenAI/xAI/Claude cargados; cada uno usa su identidad de Vault.

La captura LLM está habilitada por defecto con `LUMEN_TRACE_CONTENT=1`: mensajes, respuestas, herramientas, argumentos y resultados, con ocultación de credenciales. Independientemente, `LUMEN_TRACE_VAULT_RAW=1` guarda el intercambio con Vault, JWT y credenciales en claro. Límite por campo: 65.536 bytes, con truncamiento indicado; Tempo usa `distributor.max_attribute_bytes=131072`. Para volver a metadatos de nuevas trazas: `LUMEN_TRACE_CONTENT=0 LUMEN_TRACE_VAULT_RAW=0 bash chatbot/scripts/run.sh`. El audit log tiene su propio interruptor (sección 8).

En Grafana abre un span `xai.chat`, `openai.chat` o `anthropic.chat` y revisa `lumen.user.message`, `gen_ai.input.messages`, `gen_ai.output.messages` y `gen_ai.tool.definitions`. En `tool.*`, revisa `gen_ai.tool.call.arguments` y `gen_ai.tool.call.result`. El enlace **Ver última traza** del chat ofrece paneles legibles por llamada. Las trazas anteriores no contienen mensajes. Se captura el contenido del callback LangChain, no el cuerpo HTTP exacto ni razonamiento interno del modelo.

El visor local ofrece un diagrama interactivo con iconos por servicio, filtros de destino, flechas de petición/retorno y detalles de cada llamada. En laboratorio, **Ver valores sensibles / View sensitive values** abre los valores de OAuth y HTTP Basic (incluido `client_secret`), JWT-SVID, credenciales MySQL y cuerpos de cifrado/descifrado. Las nuevas capturas permanecen en memoria diez minutos; las capturas raw de Vault/SPIFFE mantienen la retención de trazas. [Alcance completo](chatbot/OBSERVABILITY.md#valores-de-cada-llamada).

**EN / ES** cambia títulos, explicaciones, formatos y paginación según la preferencia de Lumen; los valores originales nunca se traducen. El idioma inicial procede del navegador, salvo elección manual guardada. Grafana conserva su propio idioma. [Comprobación bilingüe](docs/manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües) · [Evidencia del 20/10](chatbot/docs/language-verification.json).

- Chat: <http://localhost:8088>
- Dashboard: <http://localhost:3000/d/lumen-iam>
- Consultar la contraseña de Grafana en Vault UI: namespace `verify` → `secrets` → `chatbot/observability`. No pegarla en una celda del notebook.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:3000/api/health
curl -fsS http://127.0.0.1:3100/ready
curl -fsS http://127.0.0.1:3200/ready
CODE
cell markdown <<'MD'
## 4. Recorrido gráfico por usuario

En IBM Verify seleccionar **Cloud Directory**. Contraseñas en `verify/secrets/chatbot/users/{reader,writer,supervisor}`.

| Acción | Lector | Gestor | Supervisor |
|---|---|---|---|
| Catálogo/inventario/bandeja enmascarada | Sí | Sí | Sí |
| Guardar solicitud de cinco pasos | No | Sí, revisión y confirmación | No |
| Revelar perfil, DNI e IBAN | No, 403 | No, 403 | Sí, Transit/Transform |
| Obtener rol Vault RW | 403 | 200 | 403 |
| Secreto administrativo | 403 | 403 | 403 |
| Búsqueda pública | Agente autónomo Tavily | Agente autónomo Tavily | Agente autónomo Tavily |

1. Lector: consultar catálogo e inventario; «Da el siguiente paso» bloquea localmente sin llamar a Vault.
2. «Comprobar límites en Vault» muestra nueve peticiones OBO reales: RO/RW/admin, Transit encrypt/decrypt y Transform encode/decode de DNI e IBAN. [Matriz y capturas actualizadas](docs/PERMISSION_PROBES.md).
3. Gestor: pedir al agente preparar Luz Noche, continuar al formulario, aceptar sugerencias ficticias con Tab, revisar y guardar. «Solicitudes» muestra la bandeja enmascarada compartida.
4. Lector y gestor no pueden revelar. Supervisor recupera el mismo registro, pero no obtiene SQL RW.
5. «Una mirada más amplia» usa Client Credentials → Agent Registry → Vault/Tavily.

[Resultados y capturas de la reconstrucción real](docs/E2E_OPENAI_VERIFICATION.md).

![Lector: bloqueo local](docs/screenshots/current/reader-write-denied.jpg)
![Gestor: solicitud guardada](docs/screenshots/current/writer-save-success.jpg)

MD
cell markdown <<'MD'
## 5. Del chat al audit log y a la traza

Copiar **Trace ID** del panel Actividad y pegarlo en el dashboard. Cada petición a Vault produce `request` y `response`, con el mismo `request.id`. El header `traceparent` contiene el `trace_id` y `span_id` de `vault.read`, también para las respuestas 403.

En un log: menú → **Show log details** → campo **TraceID** → **Abrir traza**. En Tempo: abrir el span `vault.read` → **Related logs**. El árbol muestra `deepagents.run`, llamadas `xai.chat`, `openai.chat` o `anthropic.chat`, herramientas, STS, Vault y consultas SQL o Tavily. OpenAI y Claude añaden `spiffe.mint_jwt_svid` y su intercambio `openai.token_exchange` o `anthropic.token_exchange`. El login OIDC genera una traza aparte, con usuario y rol, una vez validada su firma.

![Auditoría actual del Supervisor](docs/screenshots/current/grafana-audit.jpg)
![OpenAI, SPIFFE y catálogo OBO en Tempo](docs/screenshots/current/grafana-openai-trace.jpg)

Esto mide llamadas desde el chatbot: no instrumenta servidores internos de xAI/OpenAI, Verify, Vault o Tavily ni registra el razonamiento privado del modelo. El audit log de Vault acredita emisión/denegación de credenciales; las sentencias SQL se observan mediante spans cliente. Para auditoría independiente de SQL se necesita la auditoría propia de MySQL.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
# Pegar un Trace ID reciente de la interfaz.
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Pega un Trace ID reciente y repite la celda.'; exit 0; }
curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode "query={service=\"vault-audit\"} |= \"$TRACE_ID\"" \
  --data-urlencode since=24h --data-urlencode limit=100 \
  | jq '[.data.result[].values[][1]|fromjson|{time,type,request_id:.request.id,path:.request.path,allowed:.auth.policy_results.allowed,policies:.auth.policies,actor:.auth.metadata.actor_entity_name}]|sort_by(.time)'
CODE
cell markdown <<'MD'
## 6. Verificar correlación y modo de captura

El script consulta Tempo y Loki y comprueba los pares con el mismo `request.id` y `traceparent`. Prefiere la copia raw cuando existe y verifica igualdad de JWT y respuestas con el span; para registros protegidos comprueba HMAC. Exporta solo metadatos, booleanos y tamaños, nunca credenciales.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Pega un Trace ID reciente y repite la celda.'; exit 0; }
bash chatbot/scripts/verify-observability.sh "$TRACE_ID"
cd chatbot
/tmp/vault-chatbot-venv/bin/python -m pytest -q tests
CODE
cell markdown <<'MD'
## 7. Consultar mensajes y herramientas del LLM

Usar el ID de una consulta nueva. El informe end-to-end compara los campos capturados con Tempo y comprueba que los datos completos del formulario no se envían al modelo. El notebook se distribuye sin salidas; la celda siguiente muestra el contenido cuando se ejecuta.

[Captura histórica: Texto de entrada en el visor Lumen](docs/runs/20261014T162141Z/screenshots/25-model-input.jpg)
MD
cell code <<'CODE'
%%bash
set -euo pipefail
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Pega un Trace ID reciente y repite la celda.'; exit 0; }
curl -fsS "http://127.0.0.1:3200/api/traces/$TRACE_ID" | jq '
  [.batches[]?.scopeSpans[]?.spans[]?
   | select(.name == "xai.chat" or .name == "openai.chat" or .name == "anthropic.chat" or (.name | startswith("tool.")))
   | {name,attributes:[.attributes[]?
       | select(.key | test("^(gen_ai\\.(input.messages|output.messages|tool.definitions|tool.call.arguments|tool.call.result)|lumen\\.(user.message|model.parameters))$"))
       | {field:.key,content:(.value.stringValue|fromjson)}]}]'
CODE
awk '/^## 8\. Intercambios completos/{copy=1} copy' chatbot/OBSERVABILITY.md \
  | sed 's|](docs/|](chatbot/docs/|g; s|](scripts/|](chatbot/scripts/|g; s|](tests/|](chatbot/tests/|g; s|](../8_Lumen_|](8_Lumen_|g; s|](../docs/|](docs/|g' | cell markdown
cell code <<'CODE'
%%bash
set -euo pipefail
# Muestra deliberadamente JWT y respuestas en claro. No guardar estas salidas en el repositorio.
TRACE_ID=''
[ -n "$TRACE_ID" ] || { echo 'Pega un Trace ID reciente y repite la celda.'; exit 0; }
curl -fsS "http://127.0.0.1:3200/api/traces/$TRACE_ID" | jq '
  [.batches[]?.scopeSpans[]?.spans[]? | select(.name=="vault.read" or .name=="vault.write") |
   {name,attributes:[.attributes[]? | select(.key | test("^vault\\.(http\\.(request|response)|auth\\.jwt(\\.decoded)?)$")) |
      {field:.key,content:(.value.stringValue|fromjson)}]}]'
CODE
cell markdown <<'MD'
## Alcance y operación

- Se capturan todas las peticiones auditables posteriores a la activación del dispositivo, incluyendo las administrativas. Algunas rutas de estado/health no generan auditoría por diseño. Las acciones locales bloqueadas y el tráfico hacia otros servicios no son peticiones a Vault.
- Grafana es una consola del operador; sus credenciales no se entregan a los usuarios del chatbot. Loki/Tempo son ClusterIP sin autenticación propia, con port-forward localhost. Los campos del modelo/herramientas ocultan credenciales; el modo `LUMEN_TRACE_VAULT_RAW=1` conserva expresamente los JWT y respuestas de Vault en claro.
- Cada acción del chat tiene su propia traza. Las búsquedas externas usan temas públicos predefinidos. No se envían datos privados de MySQL a Tavily.
- `spans.jsonl` local en `/tmp/lumen-telemetry`, directorio 700/archivo 600; Tempo conserva trazas durante 7 días. Este archivo auxiliar no rota y conviene eliminarlo al finalizar el laboratorio.
- Alloy recoge stdout; una caída prolongada o rotación de logs del contenedor puede perder eventos pendientes. Esta configuración no es almacenamiento de auditoría inmutable de producción. Para ese objetivo: sink duradero redundante, retención/rotación y almacenamiento externo.
- Si se cambian ConfigMaps de Loki/Tempo/Alloy/datasources, reiniciar solo el deployment afectado. Los dashboards de Grafana se recargan automáticamente. Repetir despliegue no reinicia servicios.

Fuentes: [Auditoría Vault](https://developer.hashicorp.com/vault/docs/audit), [Headers de auditoría](https://developer.hashicorp.com/vault/api-docs/system/config-auditing), [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/), [Correlación Tempo/Loki](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/configure-trace-to-logs/), [Alloy Kubernetes](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/).
MD
jq -n --slurpfile cells "$BUILD_DIR/cells.json" '{cells:$cells[0],metadata:{kernelspec:{display_name:"Python 3 (Bash cells)",language:"python",name:"python3"},language_info:{name:"python",version:"3.12"}},nbformat:4,nbformat_minor:4}' > 7_Lumen_Observability.ipynb
printf 'Creado 7_Lumen_Observability.ipynb\n'
