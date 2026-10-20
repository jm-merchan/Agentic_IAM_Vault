# 04 · Perfil OAuth, identidades, grupos y agentes en Vault

[Índice](README.md) · Requiere [03](03-verify.md) · Siguiente: [Protección](05-proteccion.md)

**Ejecución guiada:** el paso `agentes` del [script paso a paso](PASO-A-PASO.md) comprueba OIDC y research antes de configurar entidades y registros; el siguiente paso `grupos` sincroniza las ACL de usuarios. Para retomar los fallos previos de Verify, empieza con `bash scripts/manual/paso-a-paso.sh desde verify-base`.

## 1. Configurar el perfil OAuth de Verify


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
jq -n --arg issuer "$TENANT/oauth2" '{
  issuer_id:$issuer,jwks_uri:($issuer+"/jwks"),use_jwks:true,
  user_claim:"sub",actor_claim:"actor-token.sub",supported_algorithms:["RS256"],
  jwt_type:"access_token",clock_skew_leeway:15,
  no_default_policy:true,optional_authorization_details:false
}' | vault write sys/config/oauth-resource-server/verify -
vault read sys/config/oauth-resource-server/verify
```

No se habilita `auth/jwt`: Agentic IAM acepta el JWT OAuth directamente en las operaciones del recurso. El perfil interpreta `sub` como usuario/identidad y `actor-token.sub` como actor en OBO. Se omite `audiences` por la limitación del STS Verify documentada para este flujo; no extrapolar esa decisión a otros emisores. [Referencia de Verify](https://developer.hashicorp.com/vault/ai/iam/providers/verify).

El modo `use_jwks=true` valida firma y claims con las claves públicas obtenidas por Vault. **No hace introspection del token en Verify por cada petición**; JWKS puede estar en caché. El JWT no es de un solo uso. Vault vuelve a aplicar sus políticas y RAR al acceder al recurso. [Modos de validación](https://developer.hashicorp.com/vault/ai/iam/concepts/oauth-profiles#key-validation-modes).

## 2. Escribir las políticas de aplicación

| Política | Permisos |
|---|---|
| `chatbot-reader` | Emitir SQL RO |
| `chatbot-writer` | SQL RO/RW, Transit encrypt, Transform encode |
| `chatbot-supervisor` | SQL RO, Transit decrypt, Transform decode |
| `chatbot-data-ceiling` | Techo del actor OBO: unión de las rutas anteriores |
| `chatbot-research` | Leer solamente Tavily |

Los grupos son independientes. Un usuario en varios grupos puede acumular permisos; para la demo, cada cuenta pertenece a uno de los tres grupos de Lumen.

```bash
vault policy write chatbot-data-ceiling - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
HCL
```

```bash
vault policy write chatbot-reader - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
HCL
```

```bash
vault policy write chatbot-writer - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
HCL
```

```bash
vault policy write chatbot-supervisor - <<'HCL'
path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
HCL
```

```bash
vault policy write chatbot-research - <<'HCL'
path "secrets/data/tavily" { capabilities = ["read"] }
HCL
```

Crear también las políticas vacías donde se activarán los bloqueos. No conceden ningún permiso y no deben vaciarse si ya había un bloqueo activo:

```bash
vault policy list -format=json > "$MANUAL/policies.json"
for target in xai database-read database-write decrypt; do
  if ! jq -e --arg p "lumen-block-$target" 'index($p)!=null' "$MANUAL/policies.json" >/dev/null; then
    printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write "lumen-block-$target" -
  fi
done
```

## 3. Crear entidades y aliases para los agentes

El `client_id` de Verify es el `sub` del token Client Credentials. No se crea un usuario humano para cada agente. En OBO se distinguen la entidad humana y la entidad `chatbot-oidc`.

Ejecutar cada bloque por separado, esperando a que vuelva `bash-3.2$`. Si la terminal sigue mostrando `>` después de pegar un bloque completo, pulsar **Ctrl+C** y volver a copiar ese bloque. Si Bash termina y reaparece `❯`, entrar con `bash` y cargar la sesión del paso 1 antes de continuar.

Comprobar primero que el capítulo 03 ha guardado las credenciales de **ambas** aplicaciones. Esta comprobación no modifica entidades ni muestra credenciales:

```bash
vault kv get -mount=secrets -field=client_id chatbot/oidc >/dev/null && vault kv get -mount=secrets -field=client_id chatbot/research >/dev/null
```

Si falta `chatbot/research`, volver a [03, paso 3](03-verify.md#3-crear-las-aplicaciones-oidc-y-de-investigación), seleccionar `suffix=research` y completar su configuración hasta guardar la credencial en Vault. Un archivo local de una ejecución anterior no demuestra que la aplicación siga existiendo.

Configurar un agente por pasada. Empezar por `oidc`; al terminar, repetir desde aquí cambiando la línea siguiente por `suffix=research`:

```bash
suffix=oidc
```

Construir el nombre del agente:

```bash
name="chatbot-$suffix"
```

Obtener su client ID desde Vault:

```bash
cid=$(vault kv get -mount=secrets -field=client_id "chatbot/$suffix")
```

Seleccionar su política y el requisito de RAR. **Copiar este bloque completo:**

```bash
case "$suffix" in
  oidc) policy=chatbot-data-ceiling; optional=false ;;
  research) policy=chatbot-research; optional=true ;;
  *) printf 'El agente debe ser oidc o research\n' >&2; false ;;
esac
```

Crear o actualizar la entidad:

```bash
vault write "identity/entity/name/$name" external_id="$cid" policies="$policy"
```

Obtener el ID de la entidad:

```bash
entity=$(vault read -field=id "identity/entity/name/$name")
```

Consultar los aliases actuales:

```bash
vault read -format=json "identity/entity/id/$entity" > "$MANUAL/agent-entity.json"
```

Buscar el alias por nombre y detenerse si hay duplicados:

```bash
alias_id=$(jq -r --arg name "$name" '[.data.aliases[]?|select(.name==$name)|.id]|if length>1 then error("Alias duplicado") else .[0]//empty end' "$MANUAL/agent-entity.json")
```

Crear el alias solo si falta. **Copiar el condicional completo:**

```bash
if [ -z "$alias_id" ]; then
  vault write identity/entity-alias name="$name" canonical_id="$entity" issuer="$TENANT/oauth2" external_id="$cid"
fi
```

Preparar el registro con su política techo:

```bash
jq -n --arg name "$name" --arg entity "$entity" --arg policy "$policy" --argjson optional "$optional" '{display_name:$name,entity_id:$entity,ceiling_policies:([$policy]+(if $name=="chatbot-oidc" then ["lumen-block-database-read","lumen-block-database-write","lumen-block-decrypt"] else [] end)),no_default_ceiling_policy:true,optional_authorization_details:$optional,description:"Lumen chatbot laboratory"}' > "$MANUAL/agent-registration.json"
```

Registrar el agente:

```bash
vault write agent-registry/register - < "$MANUAL/agent-registration.json"
```

Comprobar su registro:

```bash
vault read "agent-registry/registration/display-name/$name"
```

Repetir los pasos de configuración para `suffix=research` antes de pasar a la sección 4.

El actor OBO exige RAR y tiene un techo explícito. La excepción `optional_authorization_details=true` se limita al agente Tavily: su acceso autónomo queda limitado por su política de entidad. Los agentes xAI, OpenAI y Claude exigen RAR.

## 4. Crear la configuración de sesión

Ejecutar esta línea desde la raíz del repositorio, en zsh o Bash. Carga su propio entorno, consulta Vault y crea `chatbot/runtime` solo si falta. Si existe, conserva `session_secret` y la configuración actual:

```bash
bash scripts/manual/guided-run.sh bash chatbot/scripts/configure-runtime.sh
```

## 5. Sincronizar grupos de Verify a Vault y dar acceso a la app

Ejecutar únicamente la línea siguiente desde la raíz del repositorio. El script carga `.env` y la conexión privada de Vault, establece el namespace `verify` y obtiene un token administrativo nuevo. No depende de `MANUAL`, `TENANT` ni `VAULT_ADDR` definidos en tu terminal. Si sigues en un prompt `>` por un pegado anterior, pulsa **Ctrl+C** antes de ejecutar la línea.

Primero consulta los tres grupos, sus usuarios y las políticas requeridas. Si falta un grupo, se detiene antes de modificar identidades o permisos. Después sincroniza entidades/aliases por **ID de usuario** y grupos **internal** de Vault, y concede a esos grupos acceso a la aplicación OIDC.

```bash
bash scripts/manual/paso-a-paso.sh ejecutar grupos
```

Puedes comprobar los requisitos sin aplicar cambios con `bash scripts/manual/guided-run.sh bash chatbot/scripts/05-sync-groups.sh --check`.

Tras cambios de membresía, repetir la sincronización, reiniciar Lumen para cargar los IDs/nombres y obtener una sesión OIDC nueva. El JWT ya emitido conserva sus claims, pero la membresía de Vault y las políticas se evalúan con el estado del servidor.

## 6. Política bootstrap y comprobaciones

Cada línea carga su propio entorno. La política se aplica desde [bootstrap.hcl](../../chatbot/policies/bootstrap.hcl), el mismo archivo que utiliza el despliegue.

```bash
bash scripts/manual/guided-run.sh bash scripts/manual/iam.sh bootstrap
```

La app no usa root. Este bootstrap lee las credenciales OAuth de los tres agentes de modelo y su configuración; no lee `verify-admin`, Tavily, claves xAI, datos SQL ni datos protegidos. Se revoca a sí mismo tras cargarlos.

```bash
bash scripts/manual/guided-run.sh bash scripts/manual/iam.sh check
```

Fuentes locales: [04-vault-agents.sh](../../chatbot/scripts/04-vault-agents.sh), [05-sync-groups.sh](../../chatbot/scripts/05-sync-groups.sh). La prueba con JWT delegado está en [11](11-obo.md).
