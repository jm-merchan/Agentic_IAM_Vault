# Comprobación de permisos: SQL, Transit y Transform

El botón **Comprobar límites en Vault** ejecuta nueve peticiones reales. La respuesta se divide en base de datos/administración, Transit y Transform. Cada fila muestra el resultado de Vault y el permiso esperado del perfil; el resumen indica cuántas comprobaciones coinciden.

| Ruta en el namespace `verify` | Lector | Gestor | Supervisor |
|---|---|---|---|
| `database/creds/chatbot-readonly` | Permitido | Permitido | Permitido |
| `database/creds/chatbot-readwrite` | Denegado | Permitido | Denegado |
| `secrets/data/verify-admin` | Denegado | Denegado | Denegado |
| `transit/encrypt/lumen-applications` | Denegado | Permitido | Denegado |
| `transit/decrypt/lumen-applications` | Denegado | Denegado | Permitido |
| `transform/encode/lumen-dni` | Denegado | Permitido | Denegado |
| `transform/decode/lumen-dni` | Denegado | Denegado | Permitido |
| `transform/encode/lumen-iban` | Denegado | Permitido | Denegado |
| `transform/decode/lumen-iban` | Denegado | Denegado | Permitido |

La matriz corresponde al agente **Estándar / Modo actual**, sin bloqueos
administrativos. Un agente por tarea puede restringirla; la comprobación usa la
combinación activa y muestra su identidad en Vault.

Transit cifra o descifra el perfil de una solicitud. Transform tokeniza o recupera DNI e IBAN. El gestor puede proteger datos para guardarlos; el supervisor puede recuperar los originales. El lector solo consulta la proyección enmascarada.

## Cómo se comprueba

Cada ruta obtiene su propio JWT mediante OBO. Las lecturas SQL/KV usan RAR `read`; las seis peticiones POST de Transit/Transform usan RAR `update`. Se consulta Vault incluso cuando se espera una denegación: los grupos determinan la columna «Esperado», pero el resultado procede de la respuesta real.

Solo HTTP 403 se presenta como «Denegado». Errores de red, OBO o del servicio no se interpretan como un permiso denegado. En las operaciones autorizadas de descifrado/recuperación se compara además el dato recuperado con el valor ficticio original. Un resultado inesperado queda reflejado en la tabla y en el resumen.

Durante el aprovisionamiento, `04-vault-agents.sh` invoca `configure-permission-probe.sh` después de crear la configuración del runtime. Este prepara una muestra cifrada y dos tokens de datos ficticios, y los conserva en `secrets/chatbot/runtime`. Su creación es idempotente y mantiene los grupos y la clave de sesión existentes. La aplicación ya podía leer esa configuración: no se añaden permisos al token de bootstrap ni a los perfiles humanos.

Esto permite probar `decrypt` y `decode` en una instalación vacía, sin consultar solicitudes de clientes y sin depender de que antes entre un gestor. Cada prueba autorizada de `encode` crea tokens ficticios en Transform; las credenciales SQL emitidas caducan según su lease. El chat no muestra credenciales ni valores recuperados y no se modifican filas de MySQL.

## Capturas de los tres perfiles

**Lector: una ruta permitida y ocho denegadas.**

![Lector: SQL, Transit y Transform](screenshots/current/reader-permissions.jpg)

**Gestor: cinco rutas permitidas y cuatro denegadas.**

![Gestor: cifrar y tokenizar, sin revelar](screenshots/current/writer-permissions.jpg)

**Supervisor: cuatro rutas permitidas y cinco denegadas.**

![Supervisor: descifrar y recuperar, sin escribir](screenshots/current/supervisor-permissions.jpg)

## Trazas y auditoría

**Ver última traza → Ver en Grafana** muestra el span `permissions.probe` y las nueve operaciones, incluidas las denegaciones. `probe.check_count` indica el número de rutas y `probe.matches_expected` si coinciden con el perfil. Los spans `vault.read`/`vault.write` conservan HTTP status, ruta, JWT OBO y petición/respuesta conforme al modo raw del laboratorio. En Loki, filtrar por el mismo Trace ID para ver los pares request/response.

Las capturas se renovaron el **22/10/2026**. Los resultados y los Trace ID de
esta revisión están en el [informe integral](runs/20261022T140230Z-workspace-review/README.md).
Para obtener una traza navegable, ejecuta el botón en tu propia sesión: las trazas
locales están ligadas a ella y caducan. Los informes JSON son evidencia fechada.

El [informe histórico del 15/10](E2E_OPENAI_VERIFICATION.md#trazas-y-auditoría)
conserva el diagnóstico de ingestión de Alloy y su corrección; no es una
limitación pendiente de la interfaz actual.

La salida actual incluye la identidad del agente OBO de la sesión y metadatos
consultados directamente en Vault, con enlaces al registro, entidad, alias y
políticas. Esta información contextual no sustituye las nueve decisiones HTTP.
La traza identifica por separado los agentes de los proveedores y de Tavily.
Consulta [la ficha del agente y sus enlaces](manual/14-agentes-por-tarea.md#identificar-al-agente-y-pivotar-a-vault)
para el alcance de la credencial de inspección y la fecha de los metadatos.
