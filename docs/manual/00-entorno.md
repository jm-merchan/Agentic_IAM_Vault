# 00 · Preparar el entorno y los datos

[Índice](README.md) · Siguiente: [Vault](01-vault.md)

## 1. Reunir los prerrequisitos

Herramientas: Bash, curl, jq, OpenSSL, Vault CLI, kubectl, Helm 4, Minikube, Podman o Docker, uv, lsof y ripgrep (`rg`) instalado en el PATH del sistema. Para OpenAI y para el issuer de Claude, también ngrok. El lanzador existente usa macOS/launchd; aquí se muestran procesos en terminal para que cada paso sea visible. La captura OAuth interactiva usa `nc` de macOS y un navegador. El [ensayo por script](13-repeticion-script.md) utiliza curl y Perl (`HTML::Parser`, `JSON::PP`) para los formularios de Cloud Directory; no necesita navegador.

El motor de contenedores debe estar arrancado. Reserva 4 CPU y 8 GiB para Minikube y capacidad suficiente en la VM del motor. La imagen de Vault es `josemerchan/vault-xai:2.1.2-ent`, con el plugin xAI incluido; no se construye una imagen `localhost/vault-xai`.

| Entrada | Cómo obtenerla / uso |
|---|---|
| Vault Enterprise | Licencia con Agentic IAM, KMIP y Transform |
| IBM Verify | Tenant activo; URL en `VERIFY_TENANT` y cliente API administrativo (pasos abajo) |
| Oracle Container Registry | Cuenta con acceso habilitado a MySQL Enterprise; aceptar previamente los términos aplicables |
| ripgrep (`rg`) | Obligatorio en el PATH de Bash (`brew install ripgrep`). No vale el binario embebido de Cursor/VS Code |
| Tavily | API key para búsquedas de energía |
| xAI | **Management API key** capaz de crear/revocar claves; `XAI_TEAM_ID` si lo necesita la cuenta |
| OpenAI | Admin API key con Organization Administration Write, proyecto con cuota/acceso al modelo, permisos para configurar WIF |
| Claude | Organización con crédito/acceso API y permiso para crear emisores, reglas y cuentas de servicio WIF |
| ngrok, para SPIFFE | Dominio estable perteneciente a tu cuenta; OpenAI lee discovery/JWKS y Claude lo usa como issuer exacto |
| Contraseñas de laboratorio | MySQL root y usuarios reader, writer y supervisor |

### Cliente API administrativo en IBM Verify

Este cliente es el **bootstrap de aprovisionamiento**: el capítulo [03](03-verify.md) lo usa con Client Credentials para crear aplicaciones OIDC/STS, el tipo RAR, usuarios y grupos de Lumen. No es la app de login humano ni el STS OBO; esas las crea el laboratorio después. Los agentes en ejecución **no** reciben estos permisos.

1. Entra en la consola de administración del tenant. URL típica: `https://<tenant>.verify.ibm.com/ui/admin` (o el enlace **Admin** desde el portal). Necesitas un usuario administrador del tenant.
2. Abre **Security → API access → API clients**. En UI en español suele figurar como **Seguridad → Acceso de API** (a veces bajo Configuración). Guía IBM: [Creating API clients](https://www.ibm.com/docs/en/security-verify?topic=access-creating-api-clients).
3. **Add API client** / Añadir cliente API.
4. En el paso de autorizaciones (*Entitlements*), marca exactamente estas seis (los nombres visibles pueden ir traducidos; el identificador técnico es el de la columna izquierda):

| Autorización | Para qué la usa esta demo |
|---|---|
| `manageAppAccessAdmin` | Crear/actualizar aplicaciones OIDC (`vault-chatbot-*`) |
| `manageAuthDetailTypes` | Registrar el tipo RAR `vault:path_access` |
| `manageSTSClients` | Crear el cliente STS de token exchange (OBO) |
| `readUsers` | Leer usuarios SCIM al configurar identidades |
| `manageUserStandardGroups` | Crear y asignar grupos `chatbot-readers` / `chatbot-writers` / `chatbot-supervisors` |
| `manageUsersPwdReset` | Fijar la contraseña definitiva de los usuarios de laboratorio |

5. Continúa el asistente. Deja restricciones de población/grupos en los valores por defecto (sin limitar a subconjuntos) salvo que tu tenant exija lo contrario: con `manageUserStandardGroups` Verify puede rechazar ciertas restricciones de grupo.
6. En credenciales, deja el método de autenticación del cliente en el valor por defecto (*Client secret*). Pon un nombre reconocible, p. ej. `lumen-vault-admin` o `vault-verify-automation`.
7. **Save**. Copia de inmediato el **Client ID** y el **Client secret** (el secret suele mostrarse una sola vez) a `VERIFY_ADMIN_CLIENT_ID` y `VERIFY_ADMIN_CLIENT_SECRET` en `.env`.
8. `VERIFY_TENANT` es la URL base del tenant, por ejemplo `https://merchan.verify.ibm.com`: **sin** `-admin`, **sin** `/ui/admin` y **sin** barra final. El discovery OIDC (`/oauth2/.well-known/openid-configuration`) debe responder en esa base; se comprueba en la sección 4.

Si el tenant ya tiene un cliente con esas seis autorizaciones, reutilízalo: no hace falta crear otro. `remove` de la demo **conserva** este cliente administrativo y el esquema RAR compartido.

## 2. Definir nombres y secretos externos

| Elemento | Valor de la demo |
|---|---|
| Perfil/contexto Minikube | `workshop` |
| Namespaces Kubernetes | `vault`, `mysql`, `lumen-observability` |
| Namespace Vault | `verify` |
| Vault local | `https://127.0.0.1:8443` |
| Aplicación / callback | `http://localhost:8088` / `http://localhost:8088/auth/callback` |
| MySQL local | `127.0.0.1:13306`, base `scripting` |
| Grafana | `http://localhost:3000` |
| Trust domain SPIFFE | `lumen.demo` |

Desde la raíz del workspace, abrir Bash y preparar `.env` sin sustituir uno existente:

```bash
bash
set +x
umask 077
if [ ! -f .env ]; then cp .env.example .env; fi
chmod 600 .env
```

Editar `.env` siguiendo [la plantilla completa](../../.env.example). Completar `VERIFY_TENANT`, `VERIFY_ADMIN_CLIENT_ID`, `VERIFY_ADMIN_CLIENT_SECRET`, `TAVILY_API_KEY`, `ORACLE_REG_EMAIL`, `ORACLE_REG_PASSWORD`, `VAULT_LICENSE`, `MYSQL_ROOT_PASSWORD` y las tres `LUMEN_*_PASSWORD`.

Para xAI añadir `XAI_MANAGEMENT_API_KEY`; para OpenAI `OPENAI_ADMIN_API_KEY`, `NGROK_DOMAIN` y, si no existe autenticación local, `NGROK_AUTHTOKEN`. Los tres IDs OpenAI se obtienen en el capítulo 07. Para Claude, el capítulo 08 obtiene los cinco IDs WIF y no solicita API key. El dominio de esta demo es `nondemanding-indistinguishably-claude.ngrok-free.dev`; otra cuenta debe usar su propio dominio. Los valores usan sintaxis Bash, entre comillas cuando corresponda.

Los tres proveedores son prerrequisitos del selector. Mantén `LUMEN_MODEL_PROVIDER=auto` y los modelos básicos de la plantilla: `LUMEN_OPENAI_MODEL=gpt-4.1-nano`, `LUMEN_XAI_MODEL=grok-4.3` y `LUMEN_ANTHROPIC_MODEL=claude-haiku-5-5`. El proveedor inicial no excluye las otras integraciones. En una instalación manual nueva los IDs WIF se completan al llegar a 07–08; el ensayo automático requiere que ya estén guardados, antes de retirar recursos.

**No introducir `VAULT_TOKEN`, `VAULT_ADDR` ni `VAULT_CACERT` en `.env`.** Vault todavía puede no existir. Su configuración privada se genera después de `operator init`.

## 3. Crear una sesión de trabajo reutilizable

```bash
export LUMEN_ROOT="$PWD"
export LUMEN_STATE_DIR="${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}"
export MANUAL="$LUMEN_STATE_DIR/manual"
mkdir -p "$MANUAL" "$LUMEN_STATE_DIR/vault"
chmod 700 "$MANUAL" "$LUMEN_STATE_DIR/vault"
{
  printf 'export LUMEN_ROOT=%q\n' "$LUMEN_ROOT"
  printf 'export LUMEN_STATE_DIR=%q\n' "$LUMEN_STATE_DIR"
  cat <<'BASH'
set +x
set -euo pipefail
umask 077
set -a
source "$LUMEN_ROOT/.env"
set +a
export MANUAL="$LUMEN_STATE_DIR/manual"
export VAULT_ENV_FILE="$LUMEN_STATE_DIR/vault/config.env"
export TENANT="${VERIFY_TENANT%/}"
K=(kubectl --context workshop)
cd "$LUMEN_ROOT"
form_encode() {
  jq -jr 'to_entries|map((.key|@uri)+"="+(.value|tostring|@uri))|join("&")'
}
BASH
} > "$MANUAL/session.sh"
source "$MANUAL/session.sh"
```

Tras el `source` de arriba, esta misma terminal ya tiene la sesión. **No cargar `session.sh` en zsh** (prompt `❯`): activa `set -e` en el shell de login y un solo fallo cierra la terminal. En una terminal nueva:

```bash
bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
```

El prompt debe ser `bash-…$` o similar, no `❯`. Cada capítulo recuerda cómo hacerlo. Con `set -euo pipefail`, un comando que falle termina ese Bash y vuelves al zsh padre; no se pierde la app Terminal. Los archivos JSON con tokens/contraseñas permanecen en `$MANUAL`; los documentos públicos de SPIFFE se guardarán en otro directorio, que nunca debe incluir este material.

## 4. Comprobar herramientas y conectividad

Confirmar Bash + sesión. Si `$MANUAL` está vacío, el redirect del discovery intenta escribir `/verify-discovery.json` y falla con *read-only file system*.

```bash
if [ -z "${BASH_VERSION:-}" ]; then
  printf 'Entra primero en Bash: bash && source …/manual/session.sh\n' >&2
else
  : "${MANUAL:?Carga session.sh antes de continuar}"
  : "${TENANT:?VERIFY_TENANT vacío en .env}"
  printf 'MANUAL=%s\nTENANT=%s\n' "$MANUAL" "$TENANT"
fi
```

Inventario y discovery. Se deja `set +e` en todo el bloque para listar faltantes y errores de red **sin salir del shell**; al final se restaura `set -e` solo si todo fue bien.

```bash
set +e
missing=0
for tool in curl jq openssl vault kubectl helm minikube uv lsof rg nc perl ngrok; do
  if ! command -v "$tool"; then
    printf 'Falta: %s\n' "$tool" >&2
    missing=1
  fi
done
perl -MHTML::Parser -MJSON::PP -e 1 || {
  printf 'Falta: Perl HTML::Parser o JSON::PP\n' >&2
  missing=1
}
"${CONTAINER_ENGINE:-podman}" info >/dev/null || {
  printf 'Arranca Podman/Docker (CONTAINER_ENGINE=%s)\n' "${CONTAINER_ENGINE:-podman}" >&2
  missing=1
}
if [ "$missing" -ne 0 ]; then
  printf 'Corrige lo anterior y vuelve a ejecutar este bloque. La sesión sigue activa.\n' >&2
elif ! curl --fail --silent --show-error \
  "$TENANT/oauth2/.well-known/openid-configuration" \
  > "$MANUAL/verify-discovery.json"; then
  printf 'Fallo el discovery de Verify (TENANT=%s).\n' "$TENANT" >&2
else
  jq '{issuer,authorization_endpoint,token_endpoint,jwks_uri}' \
    "$MANUAL/verify-discovery.json"
  set -e
fi
```

Resultado esperado: endpoints del tenant correcto. Esta lectura no demuestra todavía que el cliente administrativo tenga permisos; se comprobarán al autenticar y llamar a la API en el capítulo 03. Usar el hostname del tenant, sin `-admin` ni `/ui/admin`.
