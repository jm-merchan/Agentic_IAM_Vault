# Validación actual e historial de reinstalación manual

[Índice](README.md) · [Evidencias de esta ejecución](../runs/20261016T064722Z-manual-script/README.md)

## Interfaz bilingüe y trazas · 20 de octubre de 2026

El [informe de idiomas](../../chatbot/docs/language-verification.json) corresponde a la implementación y despliegue de EN/ES sobre el laboratorio existente. La revisión documental posterior enlaza esa evidencia; no repite ni sustituye la instalación completa.

| Comprobación | Evidencia registrada |
|---|---|
| Pruebas locales | **194 Python y 4 JavaScript correctas**: idioma, prioridades, aislamiento por petición, redirección local, catálogo, guardrails, permisos, credenciales y visor |
| Detección del navegador | Peticiones concurrentes con `en-US`, `es-ES`, `es-MX` y francés con inglés como segunda preferencia; HTML en el idioma correspondiente |
| Elección explícita | Cookie con prioridad sobre el navegador, persistencia tras recarga/login y rechazo de idiomas no admitidos |
| Respuestas reales | Inglés con **Claude, OpenAI y xAI**; cambio de vuelta a español con **Claude**, manteniendo el historial |
| Formulario | Error de validación en inglés; paso y valor escrito conservados al cambiar ES/EN, sin guardar una nueva solicitud |
| Catálogo y bandeja | Interfaz y descripciones del catálogo en inglés; nombres de tarifas y datos originales conservados |
| Trazas | Diagrama, detalles, títulos de capturas sensibles y paginación en inglés; `client_secret` de HTTP Basic sigue disponible en el visor autorizado |
| Móvil | EN/ES visible arriba a la derecha a 390 px, sin desbordamiento horizontal |
| Despliegue | Los 13 archivos verificados de aplicación/estilos coincidían entre workspace y runtime gestionado |

Las [pruebas de idioma](../../chatbot/tests/test_i18n.py) cubren continuaciones rechazadas en ambos idiomas y conservan las comprobaciones de autorización. Las [pruebas de capturas](../../chatbot/tests/test_trace_inspection.py) comprueban que traducir títulos no altera valores ni concede acceso a otra sesión. No se afirma una nueva prueba completa de todos los permisos contra servicios reales en ambos idiomas.

Capturas: [escritorio en inglés](../../chatbot/docs/screenshots/lumen-en.png) y [móvil](../../chatbot/docs/screenshots/lumen-en-mobile.png). Recorrido reproducible en [10 · Idioma y comprobaciones bilingües](10-aplicacion.md#idioma-y-comprobaciones-bilingües). La configuración y el idioma de los portales externos de IBM Verify y Grafana no se modificaron.

### Revisión documental posterior

Se actualizaron los README, las guías de instalación, observabilidad y SPIFFE, y los notebooks 6–9 junto con sus generadores. El [informe de revisión documental](../../chatbot/docs/language-documentation-verification.json) registra las comprobaciones de enlaces y anclas locales, sintaxis Bash, estructura de notebooks y ausencia de salidas guardadas. La [validación estática del manual](validacion.json) cubre también los scripts y bloques de los demás capítulos.

Pasaron **122 pruebas locales** de idioma, capturas sensibles y configuración/recorrido manual (`test_i18n.py`, `test_trace_inspection.py`, `test_manual_configuration.py` y `test_guided_manual.py`). Esta revisión regeneró los notebooks sin ejecutar sus celdas y no reinició la aplicación ni desplegó recursos. Las pruebas de navegador e inferencias reales corresponden a la validación de implementación descrita arriba.

## Script paso a paso · 20 de octubre de 2026

El [recorrido guiado](PASO-A-PASO.md) ejecuta archivos del repositorio con un entorno nuevo para cada paso. La validación de esta revisión incluye:

- **72 pruebas locales correctas** en [test_guided_manual.py](../../chatbot/tests/test_guided_manual.py) y [test_manual_configuration.py](../../chatbot/tests/test_manual_configuration.py): fallo/reanudación, recarga de `.env`, ejecución de un único paso, exclusión de ejecuciones concurrentes, recursos existentes y credenciales inválidas. Los casos de STS, usuarios, runtime y grupos ejecutan los scripts reales con servicios simulados; se comprueba que un grupo ausente detenga el paso antes de cualquier escritura.
- Terminal real mediante PTY: entrada desde zsh a Bash 3.2, rutas con espacios, arranque fuera del repositorio, selección por número, fallo, salida, reanudación e interrupción de un proceso en curso. Las operaciones de estos casos usan archivos de prueba aislados.
- Comillas incompletas en `.env` y en el archivo del paso: se comprueba que ningún comando de esos archivos llegue a ejecutarse.
- Sintaxis de archivos Bash, Python incrustado y enlaces locales: [informe](validacion.json).
- Ejecución real de `entorno`: correcta. Menú abierto en una terminal y cerrado sin ejecutar el siguiente paso.
- Lectura autenticada del tenant: una aplicación OIDC, ninguna research y dos STS con nombre `vault-chatbot-sts`; el ID guardado en Vault coincide con uno de ellos. Esta lectura no ha modificado recursos.

No se ha ejecutado la instalación completa con el nuevo recorrido ni las inferencias de sus pasos finales. Los resultados reales se registrarán cuando se ejecuten esos pasos; los ensayos históricos de abajo no sustituyen esa comprobación.

### Corrección y ejecución real del paso de grupos

La salida adjunta del 20 de octubre mostró que el capítulo 04 todavía ofrecía el bucle antiguo: en un Bash nuevo, `MANUAL` estaba vacío y `VAULT_ADDR` no estaba configurado. Se sustituyeron los bloques de runtime, grupos, bootstrap y comprobación por llamadas a archivos que cargan su propio entorno.

Se ejecutó **`bash scripts/manual/paso-a-paso.sh ejecutar grupos` contra el laboratorio**, con resultado `OK · grupos`. La lectura posterior de Vault confirmó:

| Grupo | Miembros | Política |
|---|---:|---|
| `chatbot-readers` | 1 | `chatbot-reader` |
| `chatbot-writers` | 1 | `chatbot-writer` |
| `chatbot-supervisors` | 1 | `chatbot-supervisor` |

Verify aceptó la concesión de acceso de los tres grupos a la aplicación OIDC. La política bootstrap coincide con el archivo del repositorio. Comparando las versiones de `chatbot/runtime` antes y después, se conservaron la clave de sesión y todos los campos distintos del mapa de grupos.

También pasó la comprobación de requisitos iniciada con `MANUAL`, `TENANT` y todas las variables de conexión `VAULT_*` eliminadas del entorno del proceso. Esta evidencia valida el paso de grupos y su carga de entorno; no es una prueba completa de login OBO ni de inferencia.

## Revisión del selector de proveedores

Las guías actuales preparan las tres identidades, guardan los perfiles por separado y publican un catálogo conjunto. Se han corregido la lectura bootstrap de Claude, los nombres de capítulos y los rangos de bloques del ensayo, las verificaciones por sesión de los tres modelos y la reanudación tras actualizar JWKS en Claude. El procedimiento para un entorno existente está en [10](10-aplicacion.md#actualizar-una-instalación-existente).

[Validación estática actual](validacion.json) y pruebas en `chatbot/tests/test_manual_configuration.py`: sintaxis, enlaces, catálogo generado con entradas sintéticas, planificación de bloques y reanudación de informes. Esta revisión no ejecuta `rebuild`, crea usuarios ni aplica bloqueos al laboratorio. La verificación real del selector realizada antes de esta revisión está en [model-selection-verification.json](../../chatbot/docs/model-selection-verification.json).

## Comprobación visual manual del 19 de octubre de 2026

Se ejecutaron los capítulos 00–10 mediante Rex y se verificaron los recorridos desde Chrome contra el laboratorio local. Esta comprobación es independiente del ensayo histórico por script y no implica una reconstrucción adicional.

| Área | Resultado observado |
|---|---|
| Salud | Lumen respondió `ok` y enumeró OpenAI, xAI y Claude; Grafana, Loki y Tempo quedaron operativos |
| Permisos | Lector, gestor y supervisor obtuvieron **9/9** comprobaciones esperadas; 27/27 en conjunto |
| Solicitud | El gestor creó una solicitud sintética; perfil cifrado y DNI/IBAN tokenizados en MySQL |
| Revelado | Lector y gestor recibieron 403 de Vault; supervisor recuperó el perfil, DNI e IBAN sintéticos |
| Tavily | Búsqueda real mediante `chatbot-research`; la traza mostró `verify.client_credentials`, `vault.read` y `tavily.search`, sin OBO SQL |
| Observabilidad | Se conservaron el audit HMAC y cinco dispositivos raw filtrados; Loki mostró eventos HMAC y raw, y Tempo recibió las trazas |

La prueba de ámbito tuvo una diferencia entre proveedores: Claude y xAI rechazaron la pregunta meteorológica y resolvieron «venga» sin otra llamada al modelo o a Vault. OpenAI respondió también con un rechazo, pero su clasificador inicial permitió la consulta y produjo una llamada adicional al modelo; la autorización de Vault no se amplió. Después, una pregunta explícita sobre tarifas volvió a funcionar con los tres proveedores.

Los identificadores de solicitudes, trazas y respuestas completas se conservaron en `$MANUAL`; no se copian aquí credenciales, JWT ni datos de la solicitud.

## Ensayo histórico anterior al selector

El **16 de octubre de 2026** terminó correctamente un ciclo completo de retirada, instalación desde las guías y **102 comprobaciones funcionales**. Todo se ejecutó por script, sin navegador, notebooks ni `demo.sh start`. Vault se configuró mediante su CLI; las APIs externas, mediante curl. Las pruebas funcionales llamaron a los servicios reales de la aplicación Python, sin mocks.

## Validación adicional de Claude

Después de ese ciclo se creó la federación Claude mediante su portal y se ejecutó [08 · Claude con SPIFFE](08-claude-spiffe.md) contra el mismo Vault recién instalado. Se validaron el canje RFC 7523, el catálogo, una inferencia real con `claude-haiku-5-5`, un token nuevo por ejecución, el rechazo `jti_reused`, la audiencia fija y las denegaciones de base de datos/secreto administrativo. El verificador integrado terminó con sus cinco checks y las **137 pruebas, más dos subtests**, del chatbot pasaron.

Claude no pudo obtener las claves mediante discovery ni URL directa desde el dominio ngrok gratuito (`jwks_unavailable`). La configuración final usa las dos claves públicas de Vault en el modo **Claves en línea**. Esto obliga a actualizar el conjunto JWK en Claude después de recrear el almacenamiento de Vault; el procedimiento está en el capítulo 08. El banner de aquella ejecución mostraba **Claude · claude-haiku-5-5** y **SPIFFE JWT-SVID · Vault → Claude**.

## Qué se retiró y reconstruyó

Se inventarió la retirada con `demo.sh remove --dry-run` y se ejecutó `demo.sh remove`: **tres namespaces Kubernetes, diez volúmenes y once recursos Lumen de Verify**. La comprobación final exige namespaces con UID distintos y tres usuarios Verify nuevos.

Se conservaron `.env`, el cliente administrativo Verify, su esquema RAR compartido, Minikube/caché y el proyecto, cuenta de servicio y proveedor/mapping WIF de OpenAI. Son prerrequisitos externos: este ciclo no prueba su creación inicial. Sí prueba que el mapping existente acepta JWT-SVID firmados por el Vault recién instalado, con claves nuevas.

La instalación ejecutó **89 bloques en primer plano y siete bloques de servicios en segundo plano**, extraídos de los capítulos 00–09. Los hashes de las **96 ejecuciones** corresponden a la versión de las guías utilizada en aquel ensayo, anterior a esta revisión: [cotejo de los bloques](../runs/20261016T064722Z-manual-script/guide-block-integrity.json). Los bloques de Vault CLI del entonces capítulo 11 (ahora 12) se utilizaron además para aplicar y retirar los bloqueos durante las pruebas.

## Resultados funcionales

| Área | Resultado observado |
|---|---|
| Infraestructura | Vault Raft/TLS, init/unseal, namespace `verify`, MySQL/KMIP y observabilidad instalados de nuevo |
| Login | Authorization Code + PKCE real de lector, gestor y supervisor; cookies independientes, firma, issuer, audiencia, caducidad, state y nonce |
| Permisos | Nueve comprobaciones Vault por perfil; roles SQL, Transit, Transform y secreto administrativo |
| Solicitud | Cinco pasos con datos sintéticos; escritura del gestor e idempotencia; lector y supervisor no pueden guardar |
| Lectura | Datos enmascarados para los tres perfiles; solo supervisor recupera exactamente perfil, DNI e IBAN |
| Bloqueos | Lectura, escritura y descifrado denegados con JWT anteriores y nuevos; el JWT aún válido vuelve a funcionar al desbloquear |
| Deep Agents | Consulta del catálogo por OBO y búsqueda de energía con Tavily mediante agente registrado |
| Ámbito | Pregunta sobre el tiempo rechazada; «venga» mantiene el rechazo sin una nueva llamada a Vault/modelo |
| OpenAI | JWT-SVID de Vault → intercambio → inferencia; firma y sujeto comprobados; SVID visible en trazas y ausente de los prompts |
| xAI | Clave dinámica, caché reautorizada, reemplazo antes de caducar, inferencia con la nueva clave, bloqueo, revocación efectiva y recuperación |
| Observabilidad | **46 trazas en Tempo**, **80 peticiones a Vault** y **160 eventos raw de auditoría** correlacionados en Loki, incluyendo denegaciones |

La prueba de xAI espera el umbral real de reemplazo de la credencial; no adelanta el reloj ni simula la emisión. Las 102 comprobaciones incluyen 56 aserciones funcionales y 46 comprobaciones de trazas/auditoría. El detalle está en [workflows.json](../runs/20261016T064722Z-manual-script/workflows.json).

Esta ejecución no inspecciona visualmente NiceGUI ni genera capturas. Comprueba los servicios que utiliza la interfaz. Las capturas del 15/10 permanecen como evidencia histórica; sus IDs no corresponden al Tempo actual.

## Correcciones incorporadas durante los ensayos

| Problema observado | Corrección |
|---|---|
| Perfil Minikube ya activo | [01](01-vault.md): comprobar su estado antes de arrancarlo |
| Reloj de Podman atrasado tras suspensión | [01](01-vault.md): comprobar desfase de cinco segundos, sincronizar y reiniciar `chronyd` si estaba activo; repetir antes de los modelos y de OIDC/OBO |
| Suspensión durante una llamada con credencial de cinco minutos | [13](13-repeticion-script.md): `caffeinate -ims` durante el ensayo; mantener el Mac abierto y conectado |
| Audit vacío cerraba Bash con `set -e` | [09](09-observabilidad.md): inventario con `vault audit list -format=json` |
| Comprobación de herramientas con `set -e` salía de Bash; `$MANUAL` vacío escribía en `/` | [00](00-entorno.md): aviso de sesión, guardas `MANUAL`/`TENANT`, inventario con `set +e` |
| `source session.sh` en zsh cerraba la terminal entera | [00](00-entorno.md): exigir Bash anidado; bloque 4 sin `[ missing -eq 0 ]` bajo `set -e` |
| Esquema RAR compartido ya existente | [03](03-verify.md): inventariar y crear solo si falta |
| PATCH SCIM devolvía 406 | [03](03-verify.md): cabecera `Accept: application/scim+json` |
| Consulta auxiliar de `vault kv get` denegada con RAR | [06](06-xai.md) y [11](11-obo.md): lectura directa con `vault read secrets/data/...` |
| Array vacío ngrok con Bash 3.2 | [07](07-openai-spiffe.md): inicializar argumentos con `--inspect=false` |
| Repetición del login en la sesión curl | [11](11-obo.md): cookies nuevas por usuario y Authorization Code + PKCE sin `prompt=login` redundante |
| Revocación xAI con propagación y HTTP 400 | [06](06-xai.md): comprobación de lectura acotada; aceptar 400 solo con mensaje explícito de clave inválida |
| Timeout transitorio en inventario Verify | [13](13-repeticion-script.md): dos reintentos de GET; no repetir automáticamente POST/DELETE |
| Namespace Verify ausente o lectura denegada durante remove | [Retirada](../../scripts/demo/remove.sh): consultar con Vault CLI y distinguir ausencia de error; conservar claves ante error |
| Forwards de una ejecución manual anterior | [Parada](../../scripts/manual/stop.sh): retirar únicamente procesos identificados del laboratorio |

Las nueve pruebas unitarias del proceso de retirada también han pasado. Comprueban, entre otros casos, que un error de autorización no se interpreta como namespace ausente y que no se pierden las claves de recuperación si falla la retirada.

## Repetición y estado final

Para ejecutar otra vez el ciclo completo, seguir [13 · Repetición por script](13-repeticion-script.md):

```bash
bash scripts/manual/rehearse.sh rebuild
```

Al terminar aquel ciclo, Lumen quedó con **OpenAI `gpt-4.1-mini` y SPIFFE**, y xAI también estaba configurado. Los cuatro bloqueos quedaron inactivos. Este estado es histórico; el selector posterior usa el catálogo de tres proveedores. Accesos: [Lumen](http://localhost:8088), [Vault](https://127.0.0.1:8443/ui/) y [Grafana](http://localhost:3000/d/lumen-iam); las credenciales se recuperan como indica el [README principal](../../README.md#acceso-a-vault-y-grafana).

[Resultado conjunto](../runs/20261016T064722Z-manual-script/result.json) · [Trazas para la demostración](../runs/20261016T064722Z-manual-script/TRAZAS.md) · [Sintaxis de las guías](validacion.json) · [Comprobaciones generales](../workspace-static-checks.json).

Tokens, cookies, contraseñas y logs completos permanecen en el estado privado local. Las ejecuciones anteriores se archivan en `~/.local/state/lumen-vault-demo/manual-archives/`. Un fallo de red o una suspensión futura detiene el ensayo y requiere diagnóstico; este resultado acredita el ciclo fechado, no garantiza la disponibilidad futura de servicios externos.
