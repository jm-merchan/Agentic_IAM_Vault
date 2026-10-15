# Revisión del workspace — 14 y 15 de octubre de 2026

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

La evidencia original se concentra en el [informe del 14/10](E2E_VERIFICATION.md); la vigente está en el [informe OpenAI del 15/10](E2E_OPENAI_VERIFICATION.md). Describe los dos ciclos, las incidencias corregidas, el arranque posterior de reconciliación, los logins reales y sus resultados. No equivale a certificar un futuro estado: un nuevo `remove` elimina los datos y las trazas de esta ejecución.

## Evidencia del recorrido completo

Consultar [resultados y capturas históricos del 14/10](E2E_VERIFICATION.md) y el [directorio inmutable de ejecución](runs/20261014T162141Z/manifest.json). Los archivos anteriores bajo `chatbot/docs/screenshots` y los JSON con fechas previas son históricos; las guías activas enlazan la reconstrucción actual.

## Fuentes de contraste

- [IBM Verify para Agentic IAM](https://developer.hashicorp.com/vault/ai/iam/providers/verify).
- [Registro de agentes](https://developer.hashicorp.com/vault/ai/iam/setup-agent).
- [OAuth Resource Server y tolerancia de reloj](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server).
- [Vault en Kubernetes](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/helm/run).
