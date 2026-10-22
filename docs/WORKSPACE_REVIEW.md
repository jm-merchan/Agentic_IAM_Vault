# Revisión del workspace

## Reinstalación y correcciones verificadas · 22 de octubre de 2026

Después de la revisión local descrita abajo se ejecutaron la retirada y la
reinstalación solicitadas. [Informe y evidencias](runs/20261022T122934Z-full-e2e/README.md).
La suite final pasó **513 pruebas Python y 2 subtests**, además de **12 pruebas
JavaScript** y **137 comprobaciones reales**. Los cambios están publicados en
el runtime; las matrices de agentes, espacios personales, RAR y CIBA también pasaron.

| Hallazgo durante la ejecución real | Corrección y evidencia |
|---|---|
| La API administrativa Claude devolvía 404 pese al login OAuth válido | Preflight de acceso real al emisor/regla y modo explícito `api`/`console`. El segundo exporta solo JWKS públicas y deja la sincronización pendiente; la inferencia real sigue siendo obligatoria. Las claves se actualizaron y compararon en la consola. |
| Un cliente PDF antiguo y deshabilitado ya no exponía `clientId` | La retirada acepta únicamente el nombre, descripción, plantilla y estados exactos de ese recurso; sigue protegiendo el cliente administrador. El configurador CIBA tolera el campo ausente. Pruebas de aceptación y rechazo de recursos ajenos. |
| Tres dobles HTTP de prueba carecían del `request` que necesita la captura de trazas | Se usan respuestas `httpx.Response` con petición asociada. Suite completa con ambos modos de captura activados. |
| El guardrail rechazó la frase técnica del harness que nombraba `buscar_en_web` | Se usa una petición natural de autoconsumo solar y se comprueban por separado ámbito, llamada real y fuentes HTTPS. Se conserva el intento fallido; no se modifica el guardrail. |
| NiceGUI pasaba el cliente al parámetro keyword-only de `Timer.cancel` al cerrar páginas | Callback explícito sin argumentos. La prueba con un cliente real reprodujo el `TypeError` antes del cambio y pasa después; runtime actualizado. |

La descarga CIBA del backend produjo dos PDFs iguales y el contrato persistió
tras reiniciar. La recepción del archivo desde Chrome sigue sin confirmarse:
el botón generó una traza correcta, pero la automatización agotó la espera del
evento de descarga. El informe distingue esa limitación de las pruebas del backend.

## Revisión del 22 de octubre de 2026

Revisión local de la aplicación, instaladores y documentación. Se contrastaron los
flujos de OIDC/OBO, modelos, espacios personales y contratación CIBA con sus
políticas y pruebas. Los cambios se aplicaron a los archivos del repositorio;
no se desplegaron ni se modificaron recursos de Verify, Vault o MySQL.

| Incoherencia | Corrección y comprobación |
|---|---|
| `pytest` desde la raíz no encontraba `app` y fallaba durante la colección | `pytest.ini` fija la ruta de la aplicación y el directorio de pruebas. La suite completa se ejecuta desde la raíz. |
| Una respuesta 429/500/503 al leer el catálogo se interpretaba como ausencia de modelos | El arranque falla con un diagnóstico y revoca el bootstrap. Se mantiene el catálogo opcional únicamente para 403/404. Pruebas HTTP simuladas de los cinco casos. |
| La limpieza periódica CIBA podía vaciar el snapshot o eliminar una petición durante su formalización | La limpieza respeta el bloqueo de la operación; el sondeo vuelve a comprobar la caducidad al adquirirlo. Pruebas de limpieza concurrente y caducidad durante la espera. |
| Cancelar una tarea CIBA dejaba la petición en `waiting` con datos sensibles y un intercambio que podía haberse consumido | Tanto el inicio como el sondeo pasan a `error`, limpian el estado y propagan la cancelación. Se comprueban ambas interrupciones. |
| Una descarga PDF en espera conservaba una referencia a una sesión retirada; también podía entregar el PDF después de caducar | Se comprueba la identidad de la sesión y su vigencia tras la espera y antes de entregar el documento. Pruebas HTTP de retirada y caducidad. |
| El alta de usuarios utilizaba una contraseña provisional con `pwdReset=false`; perder la respuesta del POST podía dejar una credencial distinta de Vault | Se crea con `pwdReset=true` y se completa el PATCH de activación al reanudar. El simulador reproduce un POST completado con respuesta perdida y verifica las tres contraseñas sin recrear usuarios. Manual y script usan el mismo procedimiento. |
| El notebook 10 conservaba 11 celdas ejecutadas e impedía completar la suite invocada por `demo.sh` | Se conservaron todos los comandos y metadatos; se limpiaron salidas y contadores tras guardar una copia privada completa. |
| El instalador anunciaba que faltaba sincronizar las JWKS de Claude después de hacerlo | El mensaje final refleja la sincronización ya completada y pide ejecutar la verificación funcional. |
| La validación estática no cubría el README principal, `demo.sh`, toda la aplicación ni los notebooks | `scripts/manual/validate.py` incorpora esos archivos y detecta salidas guardadas. Un caso con archivos defectuosos comprueba que los cuatro tipos de problema se detectan. |
| La documentación mezclaba proveedor inicial con requisitos del arranque, JWT OBO con token nativo CIBA y resultados históricos con estado actual | README principal, chatbot, Verify, Okta e índice/manual actualizados. |

Las pruebas de las nuevas incidencias se ejecutaron primero contra el código
anterior y reprodujeron los fallos de catálogo, concurrencia/cancelación CIBA,
sesión de descarga y respuesta perdida del alta de usuarios.

La copia del notebook con sus salidas originales está fuera del repositorio, en
`~/.local/state/lumen-code-review/20261022T122212Z/10_OAuth2c_Verify_Vault.ipynb`,
con permisos `600`. SHA-256 original:
`cf2299241cacf147a025278de1e76a7d8d6cd1574d9cd473cdf962c57ff4914b`.
No se reescribió el historial Git ni se ejecutaron las celdas.

### Validación local

Resultado: **505 pruebas Python y 2 subtests correctos** (168,44 s), **12 pruebas
JavaScript correctas** y cero errores en la validación estática. El entorno Python
contiene 124 paquetes compatibles. También se analizaron las siete configuraciones
YAML sin claves duplicadas y los cinco JSON de configuración/aplicación.

Los comandos reproducibles están en [README](../README.md#revisión-y-pruebas-locales).
El informe de sintaxis, enlaces y notebooks está en
[validacion.json](manual/validacion.json). Se comprobó también la compatibilidad
de las dependencias con `uv pip check` y el Terraform archivado con
`terraform fmt -check` y `terraform validate`, usando los providers ya instalados
en `~/.local/share/okta-vault-agentic/data`.

Estas comprobaciones no incluyen un despliegue, inferencia, aprobación CIBA real,
pruebas contra los tenants ni una revisión visual en navegador. Las pruebas UI
Python utilizan la simulación local de NiceGUI. Los informes históricos siguientes
conservan sus fechas y alcance; no acreditan estos cambios desplegados.

## Revisión del 14 y 15 de octubre de 2026

La ruta activa es **Lumen + IBM Verify + Vault Agentic IAM**, con MySQL/KMIP, Transit/Transform, xAI dinámico, Tavily y observabilidad. Okta y el antiguo ejercicio de pagos no forman parte de la ejecución automática.

## Ampliación del 15 de octubre

La rama OpenAI usa SPIFFE JWT-SVID y token exchange, conservando OBO para datos y xAI como alternativa. El [notebook 9](../9_OpenAI_Vault_SPIFFE.ipynb) y el [nuevo informe end-to-end](E2E_OPENAI_VERIFICATION.md) documentan la reconstrucción con 11 recursos Verify retirados, nuevas claves SPIFFE y los tres perfiles.

Se añadieron reintentos solo a consultas GET de la API administrativa OpenAI tras un HTTP 503; las creaciones no se repiten automáticamente. La verificación OpenAI exporta trazas por defecto; los informes de pruebas antiguas se retiran al iniciar una comprobación nueva. `configure-model.sh` dirige OpenAI al flujo SPIFFE y deja de pedir una API key estática. Se corrigieron referencias del README, dispositivos de auditoría del notebook 7 y la pérdida de líneas de Alloy con la versión candidata 1.21.0-rc.0. Las entradas siguientes describen la revisión original del 14/10.

## Incoherencias corregidas (14 de octubre)

| Hallazgo | Corrección |
|---|---|
| Notebook 1 ejecutaba `minikube delete --all`, borraba `/tmp/vault`, inicializaba sin comprobar estado y mataba el proceso de 8443 | `demo.sh` adopta o crea, comprueba inicialización y puertos, conserva claves; la limpieza destructiva es una operación separada y explícita (`remove`) |
| Port-forward de Vault en `0.0.0.0` y claves de recuperación dependientes de `/tmp` | Nuevos túneles en `127.0.0.1`; bootstrap persistente en el directorio de estado |
| Estado Helm `failed` por conflicto SSA en el `caBundle` del injector | Misma versión/configuración con aplicación cliente de Helm 4; revisión 3 quedó `deployed` |
| El despliegue dependía de una imagen local y del código fuente del plugin | Imagen publicada `josemerchan/vault-xai:2.1.2-ent` (AMD64/ARM64); descarga directa desde Docker Hub, sin compilación local |
| Una instalación vacía se detenía al leer `kmip/config` antes de crearlo | HTTP 404 inicia la configuración; errores de permisos/servidor detienen el proceso sin modificarla. Seis pruebas de regresión |
| Se reutilizaban túneles que aún escuchaban pero apuntaban a pods eliminados | `start` renueva los túneles del contexto/namespace/ruta esperados bajo `launchd`; rechaza procesos ajenos. Seis pruebas de regresión |
| Notebook 1 montaba xAI en raíz, pero Lumen usa `verify/xai` | Catálogo global; montaje/configuración del motor de Lumen en `verify` |
| Notebook 2 reinstalaba UDF, regeneraba certificados, reiniciaba MySQL y simulaba caída KMIP en el flujo normal | Despliegue idempotente; conserva certificados/datos; prueba de `keyring_okv` activo |
| Notebook 3 dependía de una app `5_Payments_App.ipynb` inexistente y de contraseñas SQL de ejemplo | Notebook centrado en la configuración Lumen RO/RW; conexión y roles raíz existentes se conservan fuera del flujo |
| 53 celdas con salidas persistidas en notebooks 2–4, incluidas lecturas de credenciales | Notebooks de referencia regenerados sin salidas; originales conservados de forma privada fuera del workspace |
| Referencia activa a `secrets/xai` como requisito y confusión entre TTL del rol existente y TTL solicitado | Se elimina el requisito estático; petición explícita de 300 s. Rol existente conservado; 5 min/10 min solo como valores de creación |
| Revocación xAI por prefijo en una celda normal | Prueba de clave desechable y revocación únicamente de su lease |
| ID concreto de `vault-authn-entry` dentro de `02-verify-apps.sh` | Plantilla OIDC sin credenciales ni ID de instancia en `verify/config/oidc-template.json` |
| Configuración Vault base dependía de una sesión humana guardada | `configure-base.sh` configura RAR/perfil sin login humano previo; OBO sigue usando login real al ejecutar la aplicación |
| Research conservaba Authorization Code y refresh tokens de la plantilla | Cliente de búsqueda limitado a Client Credentials |
| Notebook Verify podía sobrescribir scripts actuales con copias embebidas antiguas | Usa archivos del workspace y verifica sintaxis; no los vuelve a materializar |
| Documentación indicaba tres dispositivos de auditoría después de añadir xAI | Cuatro: una salida HMAC y tres raw filtradas |
| CA por defecto en Python apuntaba a `ca.crt`, distinta del bootstrap | Fallback coherente `vault.ca`; ejecución normal utiliza la ruta explícita del estado |
| Informe del supervisor podía sobrescribir el del lector por compartir rol SQL RO | Informe separado `obo-supervisor.json` |
| Transform podía producir copias de auditoría con el mismo ID en dos nodos; la copia interna sin `auth` provocaba falsos fallos | Se selecciona la copia raw autenticada y se mantienen las comparaciones completas de JWT, cuerpo y respuesta; tres pruebas de regresión |
| `nohup` no mantenía los procesos tras terminar la ejecución automatizada; `launchd` no podía acceder al código en Google Drive | Servicios de usuario con copia de runtime fuera de CloudStorage; no se amplían permisos de macOS |
| `.gitignore` excluía `.hclic`, pero no `vault.hclic` | Patrón `*.hclic`, `.env`, temporales de importación y clave KMIP excluidos |
| `.env` conservaba `VAULT_TOKEN`, `VAULT_ADDR` y `VAULT_CACERT` antiguos, aunque no eran requisitos del preflight | Retiradas esas entradas; la carga inicial ignora credenciales Vault heredadas y las etapas posteriores cargan el bootstrap privado generado tras init/unseal |
| Inventario usado por el agente sin tabla en una instalación vacía | `01-database.sh` crea `test_encryption` cifrada y tres equipos ficticios si está vacía; las dos credenciales SQL prueban su lectura |
| Suspensión de macOS dejaba la VM atrasada y rompía TLS/JWT | Preflight comprueba reloj de Minikube; se documenta sincronización de la VM y suspensión |
| JWT recién emitidos rechazados con reloj casi idéntico | Perfil OAuth con `clock_skew_leeway=15`, igual que el cliente; seis checks OBO del supervisor repetidos correctamente |
| Pruebas unitarias añadían spans ficticios al archivo de la demo | `tests/conftest.py` aísla el exportador local y desactiva OTLP durante pytest |
| Grafana agotaba 768 MiB y su túnel quedaba detenido | Límite de 1536 MiB, objetivo Go de 768 MiB y recuperación de port-forward por `launchd`; reconexión real verificada |
| Capturas, Trace IDs y recuentos correspondían a despliegues eliminados | Documentación activa enlazada al run fechado; notebooks sin IDs de ejemplo ejecutables antiguos |

## Secretos y estado

`.env` conserva únicamente entradas externas y contraseñas iniciales, con modo 600. El bootstrap privado de Vault se genera después de init/unseal. La aplicación no hereda el root token. Se comprobó por hash que `.env` no cambió entre retirada y reconstrucción.

La eliminación real se ejecutó dos veces: tres namespaces Kubernetes, diez PV y diez recursos de Lumen en Verify. Se verificó el estado vacío y la conservación del cliente administrativo y recursos ajenos. El perfil Minikube y las cachés permanecen. Alcance: [remove](../README.md#volver-a-empezar-desde-cero).

## Validación y límites

La evidencia original se concentra en el [informe del 14/10](E2E_VERIFICATION.md); la del ciclo siguiente está en el [informe OpenAI del 15/10](E2E_OPENAI_VERIFICATION.md). Las comprobaciones posteriores, incluido EN/ES del 20/10, se enlazan en [VALIDACION](manual/VALIDACION.md). Describe los dos ciclos, las incidencias corregidas, el arranque posterior de reconciliación, los logins reales y sus resultados. No equivale a certificar un futuro estado: un nuevo `remove` elimina los datos y las trazas de esta ejecución.

## Evidencia del recorrido completo

Consultar [resultados y capturas históricos del 14/10](E2E_VERIFICATION.md) y el [directorio inmutable de ejecución](runs/20261014T162141Z/manifest.json). Cada captura e informe bajo `chatbot/docs/` acredita la ejecución fechada que lo generó. Las guías activas distinguen esas evidencias de los procedimientos para comprobar el estado actual.

## Fuentes de contraste

- [IBM Verify para Agentic IAM](https://developer.hashicorp.com/vault/ai/iam/providers/verify).
- [Registro de agentes](https://developer.hashicorp.com/vault/ai/iam/setup-agent).
- [OAuth Resource Server y tolerancia de reloj](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server).
- [Vault en Kubernetes](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/helm/run).
