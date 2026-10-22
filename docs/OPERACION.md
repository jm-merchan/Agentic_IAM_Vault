# Operación de Lumen

Esta guía reúne acceso administrativo, mantenimiento y retirada. Para instalar y
probar la demo, empieza por el [README principal](../README.md). Ejecuta los
comandos desde la raíz del repositorio.

## Acceso a Vault y Grafana


Los accesos se generan durante `./demo.sh start`. Los comandos siguientes utilizan el directorio de estado predeterminado; si configuraste `LUMEN_STATE_DIR`, sustituye `~/.local/state/lumen-vault-demo` por esa ruta.

### Vault

1. Abre https://127.0.0.1:8443/ui/.
2. Selecciona el método **Token** y deja el namespace vacío.
3. Copia el root token del laboratorio al portapapeles:

```bash
jq -jr '.root_token' \
  ~/.local/state/lumen-vault-demo/vault/cluster-keys.json | pbcopy
```

Pégalo para iniciar sesión. Dentro de Vault, selecciona el namespace **`verify`** para ver las integraciones.

### Grafana

Abre http://localhost:3000 e inicia sesión con el usuario **`lumen-admin`**. Recupera su contraseña desde Vault y cópiala al portapapeles:

```bash
(
  source ~/.local/state/lumen-vault-demo/vault/config.env
  export VAULT_ADDR VAULT_TOKEN VAULT_CACERT

  vault kv get \
    -namespace=verify \
    -mount=secrets \
    -field=password \
    chatbot/observability | pbcopy
)
```

Pega la contraseña y abre el [dashboard de Lumen](http://localhost:3000/d/lumen-iam). Los comandos copian las credenciales sin mostrarlas en la terminal; ejecuta cada uno cuando vayas a pegar su valor.

## Qué configura el arranque

1. Comprueba herramientas, `.env`, motor de contenedores y discovery de Verify.
2. Arranca/crea Minikube **workshop**, despliega/adopta Vault Enterprise con TLS y tres nodos Raft; inicializa solo un cluster vacío y desbloquea los nodos.
3. Despliega/adopta MySQL Enterprise con `keyring_okv` y KMIP; conserva datos y certificados existentes.
4. Prepara el namespace Vault **verify**, KV v2 y las entradas estáticas.
5. Configura RAR, perfil OAuth, aplicaciones OIDC/STS, usuarios, grupos, entidades, políticas y agentes registrados.
6. Crea roles MySQL RO/RW, catálogo, inventario de ejemplo, Transit, tokenización y tabla de solicitudes. Prepara los agentes por tarea, los espacios personales y CIBA; la contratación requiere su verificación y habilitación iniciales.
7. Configura los tres proveedores: xAI dinámico con TTL 5 min / máximo 10 min, OpenAI con JWT-SVID de Vault y discovery/JWKS por ngrok, y Claude con su identidad SPIFFE y federación propias. Conserva los recursos externos OpenAI de la preparación inicial.
8. Activa auditoría, aplica Grafana/Loki/Tempo/Alloy, abre puertos locales e inicia Lumen.
9. Comprueba la federación SPIFFE y una inferencia real de Claude, y ejecuta pruebas de aplicación, permisos SQL, límites del agente y búsqueda real Tavily. Un fallo devuelve código distinto de cero e identifica la etapa fallida.

Se puede repetir: reutiliza recursos por nombre, no elimina perfiles/PVC, no reinicializa Vault ni regenera secretos de clientes existentes. Actualiza configuración gestionada y reinicia Lumen para cargarla; las sesiones del chatbot se pierden en ese reinicio. Reconcilia el catálogo de tres planes y conserva las solicitudes.

Contexto fijo: `workshop`; namespaces Kubernetes: `vault`, `mysql`, `lumen-observability`; namespace Vault: `verify`. Estos nombres están fijados en los manifiestos. Una instalación nueva prescinde de injector/CSI porque Lumen no los utiliza.

### Inicialización de Vault y credenciales generadas

El orden del bootstrap es:

1. Leer las entradas externas de `.env`, sin necesitar un token de Vault.
2. Desplegar Vault y, solo si no está inicializado, ejecutar `vault operator init`.
3. Guardar el root token y las claves de desellado en `~/.local/state/lumen-vault-demo/vault/cluster-keys.json`, con permisos `600`.
4. Desellar Vault y generar `vault/config.env` dentro de ese directorio de estado, con la conexión TLS y el token para aprovisionamiento.
5. Configurar las integraciones usando ese archivo. La aplicación recibe después un token de bootstrap limitado, no el root token.

## Actualizar la aplicación

Con la infraestructura activa, para publicar el código local y reiniciar Lumen:

```bash
bash scripts/demo/start.sh
```

Se copian `chatbot/app/` y `chatbot/static/` al runtime gestionado y se renuevan los
túneles de observabilidad. El reinicio termina las sesiones y pierde conversaciones,
formularios no guardados y capturas en memoria. Las solicitudes guardadas y los
contratos confirmados persisten en los servicios.

Para reconciliar también infraestructura, políticas e integraciones, utiliza
`./demo.sh start`. En ejecución manual, sigue
[Actualizar una instalación existente](manual/10-aplicacion.md#actualizar-una-instalación-existente).

Para cambiar los modelos preconfigurados, ajusta las variables `LUMEN_*_MODEL`
en `.env`, ejecuta `bash chatbot/scripts/configure-models.sh` y reinicia Lumen.
Elegir otro proveedor desde el banner solo afecta a esa sesión y conserva su
conversación; no exige reiniciar el proceso.

## Sincronizar las claves de Claude

`LUMEN_CLAUDE_SYNC_MODE=api` usa el perfil administrativo local `ant` para
actualizar solo las claves públicas del emisor existente y comprobar su persistencia.
`console` exporta el array público y requiere guardarlo en el emisor desde la
consola. Ambos modos mantienen la comprobación posterior de federación e inferencia.
[Preparación y límites](manual/08-claude-spiffe.md).

Para sincronizar o exportar las claves actuales sin reinstalar:

```bash
bash scripts/demo/claude-issuer.sh
```

El array queda en `claude/issuer-keys.json` y el resultado en
`claude/issuer-sync.json`, dentro del directorio de estado. En modo `console`, el
informe del exportador queda pendiente: exportar no demuestra que la consola haya
guardado las claves. Tras guardarlas, comprueba la federación:

```bash
./demo.sh verify --provider anthropic
```

La rotación de claves mientras la demo permanece encendida también requiere
sincronizar las claves en línea. No hay un sincronizador periódico para Claude.

## Retirar y reconstruir

Consulta primero el inventario y los IDs que se eliminarían:

```bash
./demo.sh remove --dry-run
```

Para ejecutar esa retirada:

```bash
./demo.sh remove
```

**`remove` elimina datos de forma irreversible**: los namespaces Kubernetes `vault`, `mysql` y `lumen-observability`, todo su contenido y sus PVC. Esto incluye todos los secretos y namespaces internos de ese Vault —también los ejercicios históricos guardados allí—, las solicitudes MySQL y los logs/trazas de Loki/Tempo. Desinstala la release Helm `vault`, incluyendo sus recursos de ámbito cluster. El perfil Minikube `workshop` y otros namespaces permanecen disponibles.

En Verify elimina exclusivamente estos nombres, resolviendo y comprobando sus IDs por API:

| Tipo | Recursos eliminados |
|---|---|
| Aplicaciones | `vault-chatbot-oidc`, `vault-chatbot-research`, `vault-chatbot-xai`, `vault-chatbot-openai`, `vault-chatbot-anthropic`, `vault-chatbot-task-read`, `vault-chatbot-task-write`, `vault-chatbot-task-reveal`, `vault-chatbot-contract` y el experimento anterior `vault-chatbot-pdf-approval` |
| Cliente STS | `vault-chatbot-sts` |
| Usuarios ficticios | `lumen-reader`, `lumen-writer`, `lumen-supervisor` y `lumen-validator`, si existe |
| Grupos | `chatbot-readers`, `chatbot-writers`, `chatbot-supervisors` y el grupo `chatbot-validators` marcado como propiedad de Lumen |

Conserva `.env`, el cliente API administrativo, el esquema compartido `vault:path_access`, `vault-authn-entry`, `vault-obo-sts` y las demás cuentas/aplicaciones de Verify. No cambia Okta. Las bajas de usuarios/grupos usan `notifyType=NONE`, sin correos de notificación. Comprueba que son las cuentas ficticias de Cloud Directory y que los grupos no contienen miembros ajenos a la demo; ante duplicados o inventarios incompletos se detiene.

El grupo `chatbot-validators` se identifica por `externalId=lumen-demo:contract-validators`; se elimina el grupo, pero conserva la cuenta real seleccionada como Validador. Verify puede omitir el identificador OAuth del experimento PDF desactivado: solo se admite esa excepción para su nombre, descripción y plantilla exactos, con la aplicación y el inicio de sesión desactivados.

Primero detiene Lumen y revoca de forma síncrona los leases de `verify/xai/creds/lumen/`. Después elimina los recursos Verify, detiene los túneles gestionados, retira MySQL/observabilidad y finalmente Vault. Si Verify, la revocación o la retirada de volúmenes falla, devuelve error y conserva las claves de recuperación. No usa `revoke-force` ni elimina finalizers para ocultar fallos. Si existen PV con política `Retain`, exige resolverlos antes de retirar datos.

Tras comprobar la eliminación remota, borra del directorio de estado `vault/`, `mysql/`, `runtime/`, `vault-chatbot-storage/`, `services/`, `pids/`, `ngrok/` y `openai/`. Retira las copias compatibles de claves/conexión de `/tmp/vault` solo si coinciden con este despliegue, y el archivo local `/tmp/lumen-telemetry/spans.jsonl`. Conserva las fuentes, capturas, informes históricos, logs del lanzador y cachés de imágenes/dependencias. Por tanto, «clean» significa recursos operativos nuevos; los informes anteriores siguen siendo evidencia histórica.

`remove` requiere acceso al perfil `workshop`; si está parado, arrancarlo con `minikube start -p workshop`. Si Vault existe y ya está inicializado, debe estar desellado y disponer de su bootstrap privado para revocar las claves externas. La autenticación administrativa de Verify procede directamente de `.env`, por lo que no depende de los secretos que se van a borrar. `remove` se puede repetir tras una ejecución parcial o cuando ya se han retirado los recursos.

El inventario se guarda en `~/.local/state/lumen-vault-demo/remove-plan.json`; una retirada completada genera `last-remove.json`. `start` y `remove` comparten el bloqueo del lanzador para no ejecutarse simultáneamente. El siguiente `start` crea una nueva CA, claves de desellado/root token, datos y clientes OAuth; las contraseñas iniciales externas se conservan en `.env`.

Con las entradas externas y las federaciones preparadas, reconstruye con:

```bash
./demo.sh start
```

Si Claude usa `console`, actualiza las nuevas JWKS en el emisor antes de que pueda
pasar su verificación. CIBA vuelve a requerir su prueba real y habilitación cuando
se recrea el cliente. Sigue [Contratación CIBA](manual/17-contratacion-ciba.md).

## Estado privado y procesos

Estado, logs e informes se guardan en `~/.local/state/lumen-vault-demo/`, configurable
con `LUMEN_STATE_DIR`. El bootstrap de Vault se conserva allí y se mantiene una
copia compatible en `/tmp/vault/config.env`. Unas claves de otro clúster provocan
una parada explícita; no se sobrescriben.

Lumen y los port-forward usan servicios de usuario de `launchd` con definiciones
privadas en `services/`. Siguen activos al terminar el comando; los túneles se
recuperan si terminan tras reiniciarse un pod. No se configuran para arrancar
automáticamente al iniciar sesión en macOS. `stop` detiene esos procesos locales
y conserva el clúster y sus datos.

`start` reemplaza los túneles del contexto, namespace y destino esperados; rechaza
puertos ocupados por procesos ajenos. Solo reinicia Lumen si el proceso corresponde
al workspace o a su runtime gestionado. El código se copia a `runtime/chatbot`
fuera de Google Drive para que `launchd` pueda ejecutarlo.

La captura raw del laboratorio puede incluir JWT, respuestas de Vault y mensajes
al modelo. `LUMEN_VAULT_AUDIT_MODE`, `LUMEN_TRACE_VAULT_RAW` y `LUMEN_TRACE_CONTENT`
se controlan en `.env`. [Contenido, acceso y retención](../chatbot/OBSERVABILITY.md).

## Adoptar un laboratorio existente

Esta sección solo aplica si ya tienes recursos desplegados. El flujo de instalación desde cero utiliza las credenciales externas introducidas directamente en `.env`.

Si Vault ya está inicializado, se necesitan sus claves guardadas: el lanzador reutiliza el estado privado o migra `/tmp/vault/cluster-keys.json` del laboratorio anterior. No puede regenerar las claves de un cluster existente ni volver a inicializarlo para recuperarlas.

`bash scripts/import-env.sh` es una **migración opcional desde un laboratorio ya operativo**: recoge las entradas de Vault, `oracle.env` y `vault.hclic` sin mostrarlas. No se ejecuta al arrancar desde cero ni importa el root token; en una instalación nueva las credenciales externas se rellenan directamente en `.env`. No sobrescribe un `.env` que ya tenga la integración.

## Reloj de la VM

Después de suspender macOS, comprueba que la VM de Podman conserva la hora correcta. `start` detecta desviaciones de más de 60 segundos antes de emitir certificados o inicializar Vault; un desfase también puede invalidar JWT. Si utilizas Podman y su VM está atrasada respecto al host, consulta su nombre con `podman machine list`. Por ejemplo, para `podman-machine-default`:

```bash
podman machine ssh podman-machine-default sudo -n date -u -s "@$(date -u +%s)" </dev/null
./demo.sh start
```

El comando sincroniza el reloj de la VM con el del host. No desactiva la validación TLS ni reinicializa Vault. Durante una demostración larga puede usarse `caffeinate -i -m` en otra terminal para evitar la suspensión automática.

El perfil OAuth de Vault y el cliente aplican **15 segundos de tolerancia** al validar fechas de JWT. Evita rechazar tokens recién emitidos por pequeñas diferencias entre Verify y la VM; no corrige un reloj atrasado varios minutos. [Parámetro oficial `clock_skew_leeway`](https://developer.hashicorp.com/vault/api-docs/system/config-oauth-resource-server).
