# Validación actual e historial de reinstalación manual

## Retirada, reinstalación y verificación real · 22 de octubre de 2026

Se retiraron 3 namespaces, 10 volúmenes y 19 recursos de Verify propiedad de
Lumen. Se crearon 3 namespaces, 10 volúmenes y 17 recursos Verify con IDs nuevos;
los dos recursos antiguos restantes se retiraron definitivamente. Se conservaron
las cuentas externas, las federaciones y el Validador real.

Pasaron **513 pruebas Python y 2 subtests**, **12 pruebas JavaScript**, 18 pruebas
de infraestructura y **137 comprobaciones reales con 54 trazas**. Las matrices
adicionales cubren 12 combinaciones de agentes, 12 de espacios personales y
4 casos RAR. El Validador aprobó CIBA: se confirmó un único contrato y dos
descargas del backend devolvieron el mismo PDF, revisado visualmente.

Chrome confirmó login OIDC, 9 permisos, catálogo con Claude y persistencia del
contrato después del reinicio. El botón PDF ejecutó correctamente las llamadas
del backend, pero la automatización no recibió el evento de descarga ni pudo
confirmar el archivo guardado por Chrome. Este último paso queda sin acreditar.

La API administrativa Claude devolvió 404; se actualizaron las JWKS públicas
en la consola y se comprobaron tanto las claves guardadas como la inferencia
federada. `.env` conserva sus entradas anteriores y añade
`LUMEN_CLAUDE_SYNC_MODE=console`. El informe registra los fallos iniciales,
las correcciones y los resultados finales: [ejecución completa](../runs/20261022T122934Z-full-e2e/README.md).

## Revisión local del código y documentación · 22 de octubre de 2026

La [revisión del workspace](../WORKSPACE_REVIEW.md#revisión-del-22-de-octubre-de-2026)
corrige la carga del catálogo ante errores de Vault, la concurrencia/cancelación
CIBA, la vigencia de la sesión al descargar un contrato y la reanudación del alta
de usuarios después de perder la respuesta del POST. El manual y el script de
usuarios mantienen `pwdReset=true` hasta completar la activación. El instalador
también informa correctamente de la sincronización de claves Claude ya realizada.

Pasaron **505 pruebas Python y 2 subtests**, **12 pruebas JavaScript**,
`uv pip check`, `terraform fmt -check` y `terraform validate` del módulo archivado
de Okta. Las configuraciones YAML y JSON son válidas. La
[validación estática](validacion.json) comprueba ahora también README, entrada
`demo.sh`, Python de la aplicación y notebooks, además de los manuales y scripts.

El notebook 10 vuelve a estar sin salidas ni contadores de ejecución. Se conserva
una copia privada íntegra de su versión ejecutada, con ruta y hash en el informe;
los comandos no cambian. Esto resuelve el fallo descrito en las entradas históricas
del 20 y 21 de octubre. `pytest.ini` permite ejecutar toda la suite desde la raíz.

**Alcance:** pruebas locales con servicios simulados y simulación UI de NiceGUI.
No se desplegaron los cambios ni se hicieron llamadas reales a Verify/Vault/MySQL,
inferencias, aprobaciones CIBA o verificaciones visuales en navegador. Las
evidencias de los apartados siguientes conservan su fecha y no validan este código
en el runtime.

## Explicación del aislamiento en la traza · 21 de octubre de 2026

Se amplió **Aislamiento del espacio personal** en ES/EN con el origen del UUID,
el alias humano, la creación del secreto, los claims OBO y la comparación entre
plantilla expandida y ruta solicitada. Incluye HCL del catálogo, RAR de la ruta
y la distinción entre HTTP 200 de Verify y autorización real de Vault.
[Explicación y límites](16-espacios-personales.md).

Pasaron **67 pruebas Python enfocadas y 8 JavaScript**, además de compilar la
plantilla con la versión de Vue instalada. La comprobación del compilador se hizo
en Node sin decodificar entidades HTML; no sustituye a renderizar en un navegador.
Con **Writer + Creación**, PKCE/OBO reales produjeron **HTTP 200 en el espacio
propio y HTTP 403 en el de Supervisor**. Se comprobó que ambas trazas usan el
UUID del humano autenticado para expandir la política, conservan la ruta pedida,
los snapshots HCL y el RAR presentado, sin incluir credenciales en esa proyección.
[Informe](../../chatbot/docs/personal-isolation-explanation-verification.json).

El cambio está desplegado; los cinco archivos de aplicación modificados coinciden
con el runtime y su comprobación de salud pasó. La validación estática del manual
y `git diff --check` también pasaron. No se modificaron permisos ni secretos
personales durante estas dos lecturas. Las pruebas anteriores de 12 combinaciones
se conservan como evidencia separada.

La nueva distribución tiene columnas adaptables y ajuste de UUID/rutas largas.
**La revisión visual sigue pendiente**: la herramienta no ofrece ningún navegador
y devuelve `Sky Computer Use native pipe startup failed`. Las capturas históricas
de abajo no acreditan este panel nuevo. Después del reinicio, vuelve a entrar y
genera una operación para ver todos los metadatos nuevos; las trazas anteriores
muestran explícitamente la información que no registraron.

## Espacios personales · 21 de octubre de 2026

Se probaron **12 combinaciones** (tres usuarios y cuatro agentes), con **120 comprobaciones reales** de Verify/OBO/Vault en **2.1.2+ent**: acceso propio, techos de escritura, CAS y denegaciones cruzadas de lectura/listado/escritura. [Informe](../../chatbot/docs/personal-spaces-verification.json) · [Guía](16-espacios-personales.md). No se migró Vault ni se modificaron solicitudes compartidas.

En Chrome, Reader + Estándar leyó su secreto con HTTP 200 e intentó leer el de
Writer con HTTP 403. El enlace abrió la denegación de Vault en la traza y mostró
las entidades propietaria y destino. Se comprobó EN/ES y un ancho móvil de
390 px sin desbordamiento horizontal. [Evidencia de interfaz y runtime](../../chatbot/docs/personal-spaces-ui-verification.json)
· [Escritorio](../../chatbot/docs/screenshots/personal-spaces-desktop.png)
· [Móvil](../../chatbot/docs/screenshots/personal-spaces-mobile.png)
· [Traza](../../chatbot/docs/screenshots/personal-spaces-trace.png).

Las capturas preceden al último ajuste que conserva el borrador al cambiar de
idioma y añade el destinatario al estado de la operación. Se verificó que los
archivos desplegados coinciden; el navegador dejó de estar disponible antes de
repetir esa comprobación visual. La escritura y CAS sí se probaron contra los
servicios reales, pero no desde esta sesión del navegador.

Después se corrigió el acceso del menú: un único `lock_outline` sustituye a
`folder_lock`, con 20 px reservados al icono, 12 px de separación y texto que
puede ocupar dos líneas. El ajuste está desplegado y el runtime responde; la
verificación visual de esta corrección sigue pendiente por la desconexión del
navegador. Las capturas anteriores no acreditan este ajuste.

La suite general obtuvo **426 pruebas Python correctas, dos subtests correctos
y un fallo**, además de **seis pruebas JavaScript correctas**. El fallo corresponde
al notebook oauth2c: tiene salidas de ejecución guardadas y el test exige un
notebook sin salidas. Se conservaron esos resultados existentes. Tras los últimos
ajustes pasaron las **47 pruebas enfocadas**, la validación estática del manual y
la comprobación del runtime, sin secretos de aprovisionamiento heredados.

También se repitió el flujo anterior: **108 decisiones de Vault, 12 consultas
a MySQL y 12 rechazos de actor incorrecto**, todos correctos. Verify cortó una
conexión tras las seis primeras combinaciones; se completaron las seis restantes
al reanudar. Se revocaron los leases de prueba.
[Informe de regresión](../../chatbot/docs/task-agents-verification.json).

[Índice](README.md) · [Evidencias de esta ejecución](../runs/20261016T064722Z-manual-script/README.md)

## Parámetros RAR · 21 de octubre de 2026

El [capítulo 15](15-parametros-rar.md) añade seis escenarios opcionales con
`allowed_parameters`, `denied_parameters` y `required_parameters`. Se ejecutaron
**25 comparaciones y 50 llamadas reales a Vault**, con login PKCE y OBO reales:
Writer + Creación, Supervisor + Revelado, Supervisor + Consulta y Writer +
Estándar. Pasaron todas las comparaciones, incluidos el control permitido frente
a restricción denegada y el acceso ya denegado por usuario/techo.
[Informe](../../chatbot/docs/rar-parameters-verification.json).

El esquema anterior de Verify se amplió conservando su ID y se prepararon dos
perfiles ficticios cifrados. No se cambiaron ACL, techos ni clientes OAuth.
El clúster sigue en **Vault 2.1.2+ent**. Esta verificación cubre la ampliación
en la instalación existente; no equivale a una reinstalación completa.

Pasaron **191 pruebas Python y 6 JavaScript**, incluida la conservación del RAR
sin parámetros, rechazo de tokens con restricciones omitidas, clasificación de
errores, aislamiento de trazas y migración idempotente del esquema. Se repitió
la preparación real: conservó el esquema y los perfiles sintéticos existentes.

En Chrome se ejecutaron los escenarios permitido y combinado con Writer +
Estándar. El enlace de una denegación abrió el paso 12 de Vault con HTTP 403,
las tres restricciones y el cuerpo enviado. La consola conservó `X-Vault-Token`
y el cuerpo. Se comprobaron ES/EN, conservación de resultados y acceso desde el
panel de permisos en móvil. A 390 px la página mide 390 px y la tabla se desplaza
dentro de su contenedor. [Evidencia de UI y runtime](../../chatbot/docs/rar-parameters-ui-verification.json)
· [Escritorio](../../chatbot/docs/screenshots/rar-parameters-desktop.png)
· [Móvil](../../chatbot/docs/screenshots/rar-parameters-mobile.png)
· [Traza](../../chatbot/docs/screenshots/rar-parameters-trace.png).

## Agentes por tarea e imágenes Vault · 20 de octubre de 2026

El [capítulo 14](14-agentes-por-tarea.md) añade Consulta, Creación y Revelado
como identidades opcionales. Se probaron **12 combinaciones** de usuario y modo,
incluyendo las tres del modo original: **108 decisiones reales de Vault**,
12 consultas de MySQL y 12 rechazos de actor incorrecto en Verify.
Se revocaron los leases emitidos por cada caso.
[Informe real](../../chatbot/docs/task-agents-verification.json).

La repetición del instalador conserva el catálogo de credenciales original
OIDC/STS/runtime y los IDs y secretos de los tres clientes nuevos. Después de
repetirlo se comprobaron de nuevo Consulta con escritor, Creación con escritor y
Revelado con supervisor.

En Chrome se completó el login PKCE del escritor con Consulta; el botón de
comprobar límites mostró 9/9, incluidos los rechazos de escritura y revelado.
Se comprobó el aviso al intentar crear una solicitud, la traducción ES/EN y la
conservación del agente al cambiar de idioma. La [captura del selector](../../chatbot/docs/screenshots/task-agents.png)
muestra el modo original como selección inicial. El cambio de agente inicia una
sesión nueva; no conserva conversación ni borradores sin guardar.

Las [imágenes publicadas](../VAULT_IMAGES.md) incluyen `2.2.0` y `2.2.0-ent`
para AMD64/ARM64. Se comprobaron versión, checksum, arranque aislado, carga del
plugin xAI y manifiestos remotos. **El clúster existente permanece en
`2.1.2+ent`**: no se ha ensayado ni aplicado una migración Raft.

La regresión local excluye una comprobación preexistente que exige que el
notebook 10 no tenga salidas: la versión de ese archivo ya registrada en Git
contiene 11 celdas ejecutadas. Se conserva intacto. Los resultados finales de
pruebas y la comparación del runtime están en el
[informe de implementación](../../chatbot/docs/task-agents-implementation.json).

## Notebook oauth2c · 20 de octubre de 2026

El [notebook 10](../../10_OAuth2c_Verify_Vault.ipynb) adapta la obtención e intercambio de tokens de HashiCorp a los clientes existentes de Lumen. Incluye PKCE, Client Credentials, OBO con RAR, lectura/denegación en Vault y refresh condicional; Lumen conserva ROPC y refresh desactivados.

Pasaron **57 pruebas locales**: 13 del [notebook](../../chatbot/tests/test_oauth2c_notebook.py) y 44 de configuración manual. Se ejecutaron las celdas Bash con **oauth2c 1.21.1 real contra un servidor OAuth local simulado**, con credenciales sintéticas. Se comprobaron Basic, los scopes, desafío/verifier PKCE, subject/actor, RAR, respuestas JSON y la repetición del recorrido. La preparación/retirada del callback conserva una URI preexistente y otros cambios en la aplicación; también se comprobaron puerto ocupado, token caducado, issuer incorrecto y fallos que no deben contarse como denegaciones.

El [informe](../../verify/docs/oauth2c-notebook-validation.json) recoge las pruebas y la validación del archivo. **No se ejecutó contra el tenant real ni se emitieron credenciales reales de MySQL.** Las respuestas de Vault y la API administrativa de Verify fueron simuladas. Al ejecutar el notebook sobre el laboratorio sí se solicitan tokens reales, se añade/retira el callback indicado y la lectura positiva emite una credencial temporal.

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

## Contratación CIBA

El capítulo [17](17-contratacion-ciba.md) documenta una prueba real con Writer y Validador separado. El [informe](../../chatbot/docs/contracts-verification.json) registra las denegaciones sin CIBA, el commit, la idempotencia, la inmutabilidad y la descarga del PDF mediante OBO. Repetir la prueba crea otro borrador ficticio y requiere confirmar una nueva petición en Verify. No confundir esta prueba de servicios con una prueba visual del navegador.
