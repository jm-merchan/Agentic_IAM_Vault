# Verificación end-to-end de Lumen

**Histórico del 14/10.** Este despliegue fue eliminado. La [reconstrucción OpenAI del 15/10](E2E_OPENAI_VERIFICATION.md) recoge el estado y las capturas posteriores.

Ejecutada el **14 de octubre de 2026** sobre Minikube `workshop`, IBM Verify `merchan.verify.ibm.com` y Vault Enterprise con la imagen `josemerchan/vault-xai:2.1.2-ent`. Evidencia: [`runs/20261014T162141Z/manifest.json`](runs/20261014T162141Z/manifest.json).

Se realizaron **dos retiradas reales**, una instalación completa desde estado vacío, una reconciliación posterior de la configuración OAuth y las pruebas de la interfaz con los tres usuarios. Durante el recorrido se corrigieron las incidencias que se detallan al final. Las capturas pertenecen a este despliegue; no se reutilizaron las de los recursos eliminados.

La comprobación del botón se amplió el 15 de octubre para cubrir nueve rutas de SQL, Transit y Transform. Ver [la matriz y sus capturas actuales](PERMISSION_PROBES.md). Las capturas de tres rutas de este informe conservan el resultado de la versión del 14 de octubre.

## 1. Retirada y reconstrucción

```bash
./demo.sh remove --dry-run
./demo.sh remove
CHATBOT_VERIFY_ACCESS=1 ./demo.sh start
./demo.sh verify
```

`CHATBOT_VERIFY_ACCESS=1` activa las comprobaciones OBO al entrar por OIDC con cada usuario. Las contraseñas se recuperan de Vault; no se incluyen en este informe.

| Comprobación | Resultado | Evidencia |
|---|---|---|
| Retirada Kubernetes | Cero namespaces de la demo y cero PV restantes | [Estado limpio](runs/20261014T162141Z/final-clean-state.json) |
| Retirada IBM Verify | Eliminados tres clientes de aplicación, un STS, tres grupos y tres usuarios | [Retirada real](runs/20261014T162141Z/final-remove.json) |
| Preservación | `.env` sin cambios; cliente administrativo, recursos ajenos y perfil Minikube conservados | [Alcance e inventario](runs/20261014T162141Z/resources-after-start.json) |
| Reconstrucción | Diez IDs Verify nuevos, diez PV nuevos y namespaces con nuevos UID | [Recursos recreados](runs/20261014T162141Z/recreated-resources.json) |
| Instalación | 21 etapas completadas; Vault inicializado/desellado y MySQL con KMIP | [Arranque limpio](runs/20261014T162141Z/start.json) |
| Reconciliación OAuth | Arranque idempotente completo, conservando la solicitud guardada | [Segundo arranque](runs/20261014T162141Z/start-reconciled.json) |
| Estado final | Vault 3/3, MySQL y cuatro servicios de observabilidad disponibles | [Estado local](runs/20261014T162141Z/services-status.txt) · [Vault](runs/20261014T162141Z/vault-pods.json) |

Antes de iniciar los workflows había **tres tarifas, tres equipos y cero solicitudes**. El inventario se crea también en una instalación vacía. [Conteos iniciales](runs/20261014T162141Z/database-before-workflows.json).

## 2. Login y permisos de los tres usuarios

Los tres usuarios iniciaron sesión realmente en Chrome mediante OIDC de Verify. Sus IDs y grupos son los del despliegue nuevo: [usuarios](runs/20261014T162141Z/users.json).

| Perfil | Leer catálogo/inventario y bandeja enmascarada | Guardar solicitud | Revelar DNI/IBAN y perfil | Secreto administrativo |
|---|---|---|---|---|
| `lumen-reader` | Permitido | Bloqueo UI y Vault RW denegado | Vault Transit denegado | Denegado |
| `lumen-writer` | Permitido | Permitido: INSERT real | Vault Transit denegado | Denegado |
| `lumen-supervisor` | Permitido | Bloqueo UI y Vault RW denegado | Permitido: Transit + Transform | Denegado |

Se completaron **20 checks OBO**: [lector, 6](runs/20261014T162141Z/obo-readonly.json), [gestor, 8](runs/20261014T162141Z/obo-readwrite.json), [supervisor, 6](runs/20261014T162141Z/obo-supervisor.json). Los permisos de lectura, escritura y revelación se comprobaron por separado; una denegación esperada cuenta como prueba correcta.

![Login OIDC del nuevo cliente](runs/20261014T162141Z/screenshots/02-oidc-consent.jpg)
![Lector consulta catálogo e inventario](runs/20261014T162141Z/screenshots/03-reader-agent.jpg)
![Lector: escritura bloqueada](runs/20261014T162141Z/screenshots/06-reader-local-block.jpg)
![Gestor: revelación denegada por Vault](runs/20261014T162141Z/screenshots/19-writer-reveal-denied.jpg)
![Supervisor: SQL RO permitido, RW y administración denegados](runs/20261014T162141Z/screenshots/26-supervisor-limits.jpg)

## 3. Solicitud real y protección de datos

El gestor preparó **Luz Noche** con el agente y completó los cinco pasos: tarifa, vivienda, titular, pago y revisión. Se guardó una única solicitud ficticia: `8cd2a9fd-190b-4864-afce-1bbc41b6f97f`.

Se verificaron Tab para aceptar sugerencias, Shift+Tab sin rellenar, conservación de texto manual, rechazo de DNI incorrecto, controles válidos de DNI/IBAN, botón de sugerencia y regeneración al abrir un borrador nuevo. Los datos son sintéticos; el IBAN utiliza el banco `0000` de laboratorio. [Checks de interfaz](runs/20261014T162141Z/form-ui-checks.json).

![Solicitud preparada por el agente](runs/20261014T162141Z/screenshots/09-writer-prepare.jpg)
![Dirección y navegación con Tab](runs/20261014T162141Z/screenshots/11-form-address.jpg)
![Validación de DNI](runs/20261014T162141Z/screenshots/12-form-invalid-dni.jpg)
![Revisión antes de guardar](runs/20261014T162141Z/screenshots/17-form-review.jpg)
![Solicitud persistida](runs/20261014T162141Z/screenshots/18-writer-saved.jpg)

MySQL conserva el perfil cifrado con Transit y tokens opacos de DNI/IBAN. Las cuatro tablas están cifradas en reposo y el plugin KMIP está activo. La lectura del lector y del gestor es enmascarada; el supervisor recuperó los valores originales exactos mediante Vault. Al cerrar el diálogo, los valores revelados desaparecieron del DOM. [Persistencia](runs/20261014T162141Z/protected-storage.json) · [Revelación](runs/20261014T162141Z/reveal-ui-checks.json).

![Lector: bandeja enmascarada](runs/20261014T162141Z/screenshots/21-reader-masked.jpg)
![Supervisor: recuperación de los datos ficticios](runs/20261014T162141Z/screenshots/27-supervisor-reveal.jpg)

El formulario se comprobó a **390 px**, en claro y oscuro, sin desbordamiento horizontal. Estas dos capturas muestran un segundo borrador sin guardar, con sugerencias distintas de la solicitud persistida.

![Formulario móvil claro](runs/20261014T162141Z/screenshots/15-form-mobile.jpg)
![Formulario móvil oscuro](runs/20261014T162141Z/screenshots/16-form-mobile-dark.jpg)

## 4. Agentes autónomos y xAI dinámico

El agente registrado de búsqueda obtuvo Tavily desde Vault y ejecutó una búsqueda real. Se verificó que no puede obtener credenciales SQL ni secretos administrativos. La identidad de xAI usa Client Credentials y `xai/creds/lumen`, con una clave dinámica de 300 segundos.

Se observó emisión inicial, reutilización del mismo lease y sustitución **antes de caducar** por validez restante insuficiente. El plugin declara el lease no renovable: la aplicación solicita uno nuevo, no intenta renovarlo. Las 12 pruebas de xAI incluyen inferencia real, límites de acceso, rechazo de una clave caducada y retirada de su lease. [Ciclo de vida en la aplicación](runs/20261014T162141Z/xai-runtime.json) · [Pruebas dinámicas](runs/20261014T162141Z/xai-dynamic-verification.json).

![Búsqueda Tavily del agente autónomo](runs/20261014T162141Z/screenshots/07-tavily.jpg)
![Sustitución de la clave temporal](runs/20261014T162141Z/screenshots/08-xai-rotation-trace.jpg)

## 5. Trazas, prompts y audit log

Se correlacionaron **20 trazas, 185 spans y 37 operaciones de Vault**. Para cada operación se compararon `traceparent`, request ID, namespace, políticas, cuerpo enviado, JWT y respuesta con las copias raw autenticadas del audit log. Son 74 eventos de petición/respuesta tras deduplicar las copias internas. Todos los checks pasaron. [Informe de correlación](runs/20261014T162141Z/traces.json).

La consulta final del lector produjo dos llamadas al modelo. Se compararon 12 campos de contenido entre el visor local y Tempo: mensajes de entrada/salida, herramientas, argumentos y resultados, parámetros y texto del usuario. El DNI, IBAN, nombre, dirección, email y teléfono completos del formulario no estaban en esos mensajes. Las trazas raw de Vault sí conservan sus intercambios por configuración explícita del laboratorio. [Comprobación de contenido](runs/20261014T162141Z/model-content.json).

![Texto de entrada al modelo](runs/20261014T162141Z/screenshots/25-model-input.jpg)
![JWT OBO: usuario, grupo, actor y autorización de ruta](runs/20261014T162141Z/screenshots/32-obo-jwt-claims.jpg)
![Revelación: cuatro operaciones de Vault sin denegaciones](runs/20261014T162141Z/screenshots/30-grafana-reveal-audit.jpg)
![Lector: una operación permitida y dos denegaciones](runs/20261014T162141Z/screenshots/31-grafana-reader-denials.jpg)

### Enlaces al despliegue verificado

Los enlaces siguientes incluyen un rango temporal absoluto. Requieren iniciar sesión en Grafana como `lumen-admin` (contraseña en Vault `verify/secrets/chatbot/observability`). Tempo/Loki retienen siete días; otro `remove` elimina ese contenido. Las capturas y los informes permanecen en el workspace.

| Flujo | Traza Tempo | Audit log correlacionado |
|---|---|---|
| Catálogo e inventario | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22b123f1c4eb409325b27b2909f8f05a6f%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=b123f1c4eb409325b27b2909f8f05a6f&var-audit_mode=raw) |
| Guardar solicitud | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%228a28f5caadcebb0576c7ef24265d02f7%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=8a28f5caadcebb0576c7ef24265d02f7&var-audit_mode=raw) |
| Gestor: revelación denegada | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22b2640481a5089f9b85b6e0d85e088f02%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=b2640481a5089f9b85b6e0d85e088f02&var-audit_mode=raw) |
| Supervisor: revelar | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22b93a149ee494649293b8c1d3a8ff0796%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=b93a149ee494649293b8c1d3a8ff0796&var-audit_mode=raw) |
| Lector: comprobar límites | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%2202e4b62df97ae9259edb8135d81e7aa5%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=02e4b62df97ae9259edb8135d81e7aa5&var-audit_mode=raw) |
| Agente Tavily | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%2297cd790adf60665a7f71eae7f2aa045f%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=97cd790adf60665a7f71eae7f2aa045f&var-audit_mode=raw) |
| Rotación xAI | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%22af3fb267a674b0c091ec601024af2cb6%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=af3fb267a674b0c091ec601024af2cb6&var-audit_mode=raw) |
| Consulta enmascarada y prompts | [Abrir traza](http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=%7B%22lumen%22%3A%7B%22datasource%22%3A%22lumen-tempo%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22queryType%22%3A%22traceql%22%2C%22query%22%3A%222fde3c3b0ca8b8f7c1511c7378b0bd8e%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22lumen-tempo%22%7D%7D%5D%2C%22range%22%3A%7B%22from%22%3A%221791994860000%22%2C%22to%22%3A%221792001936009%22%7D%7D%7D) | [Abrir logs](http://localhost:3000/d/lumen-iam?from=1791994860000&to=1792001936009&var-trace=2fde3c3b0ca8b8f7c1511c7378b0bd8e&var-audit_mode=raw) |

## 6. Incidencias resueltas durante la ejecución

| Hallazgo | Corrección y comprobación |
|---|---|
| Inventario ausente al instalar desde cero | Tabla cifrada y tres equipos de ejemplo; segunda retirada/instalación y lectura real verificadas |
| Suspensión de macOS atrasaba el reloj de la VM | Preflight de reloj y sincronización; TLS permanece validado |
| JWT recién emitidos rechazados por `iat`/`nbf` | `clock_skew_leeway=15` en perfil OAuth, igual que el cliente; tres logins y 20 checks OBO repetidos |
| Pruebas unitarias mezclaban spans ficticios con la demo | Exportación local temporal y OTLP desactivado durante pytest |
| Grafana agotaba 768 MiB y el túnel no se recuperaba | 1536 MiB y objetivo Go de 768 MiB; `launchd` reinicia túneles. Terminación deliberada y recuperación verificadas |

![Dashboard recuperado tras reiniciar el túnel](runs/20261014T162141Z/screenshots/33-grafana-restored.jpg)

[Incidencias](runs/20261014T162141Z/incidents.json) · [Recuperación del túnel](runs/20261014T162141Z/forward-recovery.json). El error intermedio de reloj se documenta; no se incluye como una traza correcta en el informe de 20 trazas.

## 7. Resultado y material actualizado

- 74 pruebas de aplicación y dos subcasos.
- 18 comprobaciones de infraestructura y privilegios.
- 20 checks OBO mediante las sesiones reales de los tres perfiles.
- 12 pruebas de secretos dinámicos xAI.
- 20 trazas reales correlacionadas con Vault; formulario, revelación, Tab y móvil comprobados visualmente.

[`demo.sh verify`](runs/20261014T162141Z/verify-final.json) pasó tras las correcciones. Se actualizaron el [README principal](../README.md), la [guía de Lumen](../chatbot/README.md), la [guía de observabilidad](../chatbot/OBSERVABILITY.md), la [revisión del workspace](WORKSPACE_REVIEW.md) y los notebooks [6](../6_Lumen_Chatbot_Vault_IAM.ipynb), [7](../7_Lumen_Observability.ipynb) y [8](../8_Lumen_Protected_Applications.ipynb). Los informes antiguos de Okta y del bootstrap Verify están identificados como históricos.

Los JSON publicados contienen metadatos y comprobaciones; los tokens, claves y respuestas raw permanecen en los servicios del laboratorio y en el estado privado, no en este informe. El estado se verificó en la fecha indicada; la retención, un reinicio de la sesión de Lumen o una nueva retirada pueden cambiar la disponibilidad de las vistas en vivo.
