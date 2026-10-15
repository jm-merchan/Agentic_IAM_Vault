#!/usr/bin/env bash
# Notebooks are explanations/wrappers; deployment code has a single source.
set -euo pipefail
cd "$(dirname "$0")/.."
work=$(mktemp -d /tmp/lumen-core-notebooks.XXXXXX)
trap 'rm -rf "$work"' EXIT
new() { printf '[]' > "$work/cells.json"; }
cell() {
  cat > "$work/source"
  jq --arg kind "$1" --rawfile text "$work/source" '.+[{id:("cell-"+(length|tostring)),cell_type:$kind,metadata:{},source:($text|split("\n")|map(.+"\n")|.[0:-1])}+(if $kind=="code" then {execution_count:null,outputs:[]} else {} end)]' "$work/cells.json" > "$work/next.json"
  mv "$work/next.json" "$work/cells.json"
}
save() {
  jq '{cells:.,metadata:{kernelspec:{display_name:"Python 3 (IPython + Bash)",language:"python",name:"python3"},language_info:{name:"python"}},nbformat:4,nbformat_minor:5}' "$work/cells.json" > "$1"
}
new
cell markdown <<'MD'
# Vault Enterprise en Minikube

La demo completa se inicia desde la raíz con **`./demo.sh`**. Este notebook documenta solo la etapa de Vault y usa los mismos scripts, sin borrar perfiles de Minikube ni reinicializar un cluster existente.

[Instalación y secretos de entrada](README.md) · [Revisión del workspace](docs/WORKSPACE_REVIEW.md).

Preparar `.env` a partir de `.env.example`: licencia, credenciales externas de integración y configuración de la imagen. No añadir `VAULT_TOKEN`, `VAULT_ADDR` ni `VAULT_CACERT`: el lanzador genera el bootstrap después de inicializar Vault. El estado generado (CA, claves de inicialización, token administrativo, logs y PID) se guarda en `~/.local/state/lumen-vault-demo`, fuera de `/tmp` y del workspace. `LUMEN_STATE_DIR` permite otra ubicación. Para adoptar un Vault ya inicializado se necesitan sus claves guardadas; no se regeneran.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
./demo.sh check
CODE
cell markdown <<'MD'
## Despliegue reejecutable

Crea o arranca el perfil `workshop`; conserva los recursos existentes. En una instalación vacía descarga de Docker Hub la imagen `josemerchan/vault-xai:2.1.2-ent` con el plugin xAI incluido (AMD64/ARM64), despliega tres nodos Raft con TLS, inicializa una sola vez y desbloquea los nodos. `.env` permite configurar `VAULT_IMAGE_REPOSITORY` y `VAULT_IMAGE_TAG`. El puerto 8443 escucha en `127.0.0.1`.

Si ya existe Vault, comprueba la imagen y adopta las claves del laboratorio anterior; no reemplaza la imagen ni regenera certificados. El catálogo del plugin es global, pero el motor xAI utilizado por Lumen se configura en `verify`.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/vault.sh
CODE
cell code <<'CODE'
%%bash
source scripts/demo/common.sh
load_inputs
load_vault
vault status
kubectl --context workshop -n vault get pods
helm --kube-context workshop -n vault list
CODE
cell markdown <<'MD'
Para reanudar, usar `./demo.sh start`; no ejecutar `minikube delete --all`, borrar claves manualmente ni volver a hacer `operator init`. `./demo.sh stop` detiene solo procesos locales, conservando cluster y datos. Para retirar el laboratorio completo, revisar `./demo.sh remove --dry-run` y ejecutar `./demo.sh remove`: elimina los tres namespaces/PVC y los recursos Lumen de Verify, conserva `.env` y permite un nuevo `start`. [Alcance de la eliminación](README.md#volver-a-empezar-desde-cero). La inicialización de un solo fragmento es una simplificación del laboratorio.
MD
save 1_Deploy_Vault_minikube.ipynb

new
cell markdown <<'MD'
# MySQL Enterprise con KMIP

`./demo.sh` incluye esta etapa. Reutiliza `mysql/mysql-enterprise-0`; una instalación vacía usa MySQL Enterprise 8.3.0, con la variante `aarch64` en ARM64. Las credenciales del registro Oracle y la contraseña inicial están en `.env`. El acceso al registro debe estar habilitado previamente en la cuenta Oracle.

Vault sirve KMIP en `vault-kmip.vault.svc.cluster.local:5696`. MySQL carga `keyring_okv`; las tablas de Lumen usan `ENCRYPTION='Y'`. Los certificados de cliente existentes se conservan.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/mysql.sh
CODE
cell markdown <<'MD'
## Comprobar plugin y cifrado

La consulta usa la contraseña del entorno del pod y no la muestra. Las tablas aparecerán después de ejecutar la etapa de roles de base de datos.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
kubectl --context workshop -n mysql exec -i mysql-enterprise-0 -c mysql -- \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch' <<'SQL'
SELECT PLUGIN_NAME, PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME='keyring_okv';
SELECT NAME, ENCRYPTION FROM INFORMATION_SCHEMA.INNODB_TABLESPACES WHERE NAME LIKE 'scripting/%';
SQL
CODE
cell markdown <<'MD'
La demo automática no cambia el puerto KMIP para simular fallos, no rota la master key de InnoDB y no reinstala funciones UDF. Eran ejercicios manuales del laboratorio previo; no son requisitos de Lumen. Tampoco reinicia MySQL en cada ejecución ni elimina sus PVC.
MD
save 2_vault-demo-kmip-mysql.ipynb

new
cell markdown <<'MD'
# Database Secrets Engine: Lumen RO/RW

`./demo.sh` incluye la creación del catálogo, tablas y roles. Se reutiliza MySQL/KMIP del [notebook 2](2_vault-demo-kmip-mysql.ipynb). La conexión y los roles de la aplicación están en el namespace Vault **verify**, no en el namespace raíz.

| Rol | Privilegios SQL | TTL / máximo |
|---|---|---|
| `chatbot-readonly` | SELECT sobre `scripting.*` | 120 s / 300 s |
| `chatbot-readwrite` | SELECT, INSERT, UPDATE, DELETE sobre `scripting.*` | 120 s / 300 s |

Vault administra la cuenta `vault_chatbot_admin` y rota su contraseña al crear la conexión. La aplicación solicita credenciales con OBO y RAR; el perfil humano, el límite del agente y el RAR deben permitir la ruta.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/01-database.sh
CODE
cell code <<'CODE'
%%bash
source verify/scripts/common.sh
for role in chatbot-readonly chatbot-readwrite; do
  vault read -format=json "database/roles/$role" | jq --arg role "$role" '{role:$role,db_name:.data.db_name,default_ttl:.data.default_ttl,max_ttl:.data.max_ttl,creation_statements:.data.creation_statements}'
done
CODE
cell markdown <<'MD'
## Verificación

Después del despliegue completo, la comprobación valida SELECT, permite INSERT con RW, deniega INSERT con RO y hace rollback. Comprueba además Tavily y los límites del token de bootstrap. Las pruebas OBO por usuario requieren su login real en Verify.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/test-infrastructure.sh
CODE
cell markdown <<'MD'
Las antiguas conexiones `database/config/mysql` y el static role `payments-app` del namespace raíz pertenecen a otro ejercicio; si existen se conservan, pero Lumen no los utiliza. No se incluye la aplicación `5_Payments_App.ipynb`, que no forma parte de este workspace.

El [notebook 8](8_Lumen_Protected_Applications.ipynb) añade Transit/Transform. El supervisor usa SQL RO y permisos separados para revelar datos; el gestor usa SQL RW y puede proteger datos, sin revelarlos.
MD
save 3_Database_Secret_Engine.ipynb

new
cell markdown <<'MD'
# xAI: credenciales dinámicas de Vault

`./demo.sh` incluye estas etapas. El plugin viene incluido en la imagen `josemerchan/vault-xai:2.1.2-ent` publicada en Docker Hub; no requiere compilación ni una copia local de su repositorio. La management key entra por `XAI_MANAGEMENT_API_KEY`, se custodia en `verify/secrets/xai_mgmt` y configura `verify/xai`.

La aplicación utiliza **Client Credentials** de `chatbot-xai` para leer `xai/creds/lumen?ttl=300`. No lee `secrets/xai`. En una instalación vacía el rol tiene TTL 5 min, máximo 10 min y caducidad nativa; en una existente se conserva el rol configurado por el usuario y se comprueba que admite el TTL solicitado.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash scripts/demo/xai.sh
bash chatbot/scripts/configure-xai.sh
CODE
cell markdown <<'MD'
## Configuración sin mostrar claves
MD
cell code <<'CODE'
%%bash
source verify/scripts/common.sh
vault read -format=json xai/config | jq '.data|{api_endpoint,team_id}'
vault read -format=json xai/roles/lumen | jq '.data|{acls,ttl,max_ttl,set_native_expiry}'
CODE
cell markdown <<'MD'
## Probar inferencia y caducidad real

La prueba emite una clave desechable de 60 s, llama a Grok, comprueba denegaciones y espera a su caducidad. Solo revoca su propio lease. No imprime la clave, no revoca por prefijo y no afecta las claves que esté utilizando Lumen.
MD
cell code <<'CODE'
%%bash
set -euo pipefail
bash chatbot/scripts/verify-xai.sh
CODE
cell markdown <<'MD'
El plugin actual no implementa renovación. Lumen reutiliza una clave mientras cubre el presupuesto de ejecución y solicita otra cuando quedan 210 s o menos. Vault revoca la anterior al expirar y xAI aplica su caducidad nativa. Ver [ciclo de vida y trazas](chatbot/README.md#xai-con-claves-dinámicas).
MD
save 4_XAI_Secret_Engine.ipynb
