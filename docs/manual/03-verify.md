# 03 · Aplicaciones, RAR, STS y usuarios en IBM Verify

[Índice](README.md) · Requiere [01](01-vault.md) · Siguiente: [Vault IAM](04-vault-iam.md)

**Para ejecutar y reanudar este capítulo**, utiliza `bash scripts/manual/paso-a-paso.sh desde verify-base`. El [recorrido guiado](PASO-A-PASO.md) separa RAR, OIDC, research, STS y usuarios en pasos ejecutables, carga el entorno y renueva el token en cada uno. Los bloques de abajo quedan como referencia detallada de las operaciones.

Ejecutar cada bloque por separado en la misma sesión **Bash**, desde la raíz del proyecto. Copiar solo su contenido y esperar a que vuelva el prompt `bash-3.2$` (o equivalente) antes de pegar el siguiente. Los comandos simples ocupan una sola línea, aunque el visor los muestre ajustados al ancho de la ventana.

Si después de pegar un bloque completo la terminal sigue mostrando `>`, pulsar **Ctrl+C** para cancelar la entrada pendiente y volver a copiar ese bloque. No pegar el siguiente ni intentar cerrar a mano una comilla. Los condicionales `if … fi` y el bucle `for … done` se copian completos; mientras Bash los recibe puede mostrar `>`.

Si un error termina Bash y reaparece el prompt de zsh (`❯`), ejecutar primero `bash` y después los tres bloques de carga de sesión del paso 1. Restaurar también las variables del paso interrumpido, como `ROLE=reader`. Las variables de la sesión Bash anterior no se recuperan en el shell padre. Recargar la vista de este archivo si todavía muestra comandos simples partidos con `\` al final de línea.

## 1. Obtener un token administrativo

Cargar la sesión del capítulo 00 desde Bash:

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
```

Cargar la conexión a Vault:

```bash
source "$LUMEN_STATE_DIR/vault/config.env"
```

Seleccionar el namespace `verify`:

```bash
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

Guardar la credencial administrativa en el archivo privado:

```bash
vault kv get -format=json -mount=secrets verify-admin | jq '.data.data' > "$MANUAL/verify-admin.json"
```

Preparar las cabeceras para solicitar el token:

```bash
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+ "\nContent-Type: application/x-www-form-urlencoded\n"' "$MANUAL/verify-admin.json" > "$MANUAL/verify-basic.headers"
```

Solicitar el token administrativo:

```bash
curl --fail --silent --show-error "$TENANT/oauth2/token" --header "@$MANUAL/verify-basic.headers" --data 'grant_type=client_credentials' > "$MANUAL/verify-admin-token.json"
```

Preparar las cabeceras para las siguientes llamadas a Verify:

```bash
jq -jer '"Authorization: Bearer "+.access_token+ "\nContent-Type: application/json\nAccept: application/json\n"' "$MANUAL/verify-admin-token.json" > "$MANUAL/verify.headers"
```

Repetir este paso si expira el token de administración. `curl --fail` detiene el bloque cuando recibe un error HTTP; no continuar a partir de un JSON vacío. Las respuestas con secretos se guardan en archivos, sin imprimirlas.

## 2. Registrar el tipo RAR `vault:path_access`

[rar-schema.json](../../verify/config/rar-schema.json) exige `type`, `path` y `capabilities`; permite `read/create/update/delete/sudo/list/deny` y las propiedades opcionales `allowed_parameters`, `denied_parameters` y `required_parameters`. Rechaza otras propiedades. Los tokens anteriores sin parámetros siguen siendo válidos. Inspeccionar el inventario primero:

Descargar el inventario de tipos RAR:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/auth-detail-types" > "$MANUAL/rar-list.json"
```

Mostrar las coincidencias de `vault:path_access`:

```bash
jq '[..|objects|select(.type?=="vault:path_access")|{id,type}]|unique' "$MANUAL/rar-list.json"
```

Revisar el esquema local:

```bash
cat verify/config/rar-schema.json
```

Los siguientes pasos crean el tipo solo cuando el inventario anterior no lo contiene. Si existe, conservan su ID. El reconciliador amplía únicamente el esquema anterior conocido de Lumen con los tres campos opcionales; cualquier otra diferencia se trata como conflicto. Conserva descripción, consentimiento y demás ajustes del tipo existente.

Obtener el ID existente. Si hay más de uno, el comando falla:

```bash
RAR_ID=$(jq -r '[..|objects|select(.type?=="vault:path_access")|.id]|unique| if length>1 then error("RAR duplicado") else .[0]//empty end' "$MANUAL/rar-list.json")
```

Crear el tipo únicamente si falta. **Copiar este condicional completo, desde `if` hasta `fi`, y esperar a que vuelva el prompt:**

```bash
if [ -z "$RAR_ID" ]; then
  jq -n --rawfile schema verify/config/rar-schema.json '{ type:"vault:path_access",description:"Vault path and capabilities for delegated access", schema:$schema,inlineMode:true, consentInlineText:("<div>Permitir al agente las operaciones solicitadas en Vault.</div>"|@base64) }' > "$MANUAL/rar-create.json"
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --data-binary "@$MANUAL/rar-create.json" "$TENANT/v1.0/auth-detail-types" > "$MANUAL/rar-created.json"
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/auth-detail-types" > "$MANUAL/rar-list.json"
fi
```

Confirmar que existe exactamente un ID:

```bash
RAR_ID=$(jq -er '[..|objects|select(.type?=="vault:path_access")|.id]|unique| if length==1 then .[0] else error("RAR duplicado o ausente") end' "$MANUAL/rar-list.json")
```

Reconciliar el esquema conocido y descargar su configuración. El script obtiene un token administrativo nuevo y no modifica clientes OAuth ni políticas de Vault:

```bash
bash verify/scripts/configure-rar.sh
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/auth-detail-types/$RAR_ID" > "$MANUAL/rar-check.json"
```

Comparar el esquema de Verify con el archivo local:

```bash
jq -e --slurpfile schema verify/config/rar-schema.json '(.schema|fromjson)==$schema[0]' "$MANUAL/rar-check.json"
```

Resultado esperado: **`true`**. Si devuelve `false` o un error, detenerse y revisar antes de continuar.

## 3. Crear las aplicaciones OIDC y de investigación

La [plantilla OIDC](../../verify/config/oidc-template.json) es el payload de aplicación de Verify (`templateId=998`). Se usan strings `"true"`/`"false"` en los campos de la API que así lo requieren.

| App | Grant | Uso |
|---|---|---|
| `vault-chatbot-oidc` | Authorization Code + PKCE y Client Credentials | Login humano y actor OBO |
| `vault-chatbot-research` | Client Credentials | Agente autónomo que recupera Tavily |
| `vault-chatbot-xai` / `vault-chatbot-openai` | Client Credentials + RAR | Se crean en sus capítulos |

Descargar el inventario de aplicaciones:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
```

Mostrar sus nombres y enlaces:

```bash
jq '[._embedded.applications[]|{name,url:._links.self.href}]' "$MANUAL/apps.json"
```

Revisar la plantilla local:

```bash
cat verify/config/oidc-template.json
```

Los siguientes pasos configuran una aplicación por pasada: primero `oidc` y después `research`. Se reutiliza una app con el nombre exacto o se crea si está ausente. Primero se obtiene su client ID; después se configura `may_act.client_id` en los tokens humanos. El claim `groups` usa el atributo Verify `sourceId=4` del tenant de referencia; comprobar su correspondencia con grupos si se adapta a otro tenant.

Seleccionar la aplicación. En la primera pasada se usa `oidc`; para la segunda, ejecutar `suffix=research` antes de repetir estos pasos:

```bash
suffix=${suffix:-oidc}
```

Construir el nombre de la aplicación:

```bash
name="vault-chatbot-$suffix"
```

Actualizar el inventario:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
```

Buscar el ID por nombre exacto. Si hay duplicados, el comando falla:

```bash
app_id=$(jq -r --arg name "$name" '[._embedded.applications[]|select(.name==$name)| ._links.self.href|split("/")[-1]]| if length>1 then error("Nombre duplicado") else .[0]//empty end' "$MANUAL/apps.json")
```

Crear la aplicación solo si falta. **Copiar este condicional completo, desde `if` hasta `fi`:**

```bash
if [ -z "$app_id" ]; then
  jq --arg name "$name" '.+{name:$name,description:"Vault IAM chatbot laboratory"}' verify/config/oidc-template.json > "$MANUAL/create-app.json"
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --data-binary "@$MANUAL/create-app.json" "$TENANT/v1.0/applications" > "$MANUAL/created.json"
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
  app_id=$(jq -er --arg name "$name" '._embedded.applications[]|select(.name==$name)| ._links.self.href|split("/")[-1]' "$MANUAL/apps.json")
fi
```

Descargar la configuración de la aplicación:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications/$app_id" > "$MANUAL/app.json"
```

Obtener su client ID:

```bash
cid=$(jq -er .providers.oidc.properties.clientId "$MANUAL/app.json")
```

Preparar la configuración de OIDC y los claims:

```bash
jq --arg cid "$cid" --arg suffix "$suffix" ' .providers.oidc.applicationUrl="http://localhost:8088" | .providers.oidc.properties.redirectUris=["http://localhost:8088/auth/callback"] | .providers.oidc.properties.grantTypes.ropc="false" | .providers.oidc.properties.grantTypes.authorizationCode=(if $suffix=="oidc" then "true" else "false" end) | .providers.oidc.properties.grantTypes.clientCredentials="true" | .providers.oidc.properties.generateRefreshToken="false" | .providers.oidc.properties.accessTokenExpiry=600 | .providers.oidc.token.accessTokenType="jwt" | .providers.oidc.requirePkceVerification="true" | .providers.oidc.token.attributeMappings=(if $suffix=="oidc" then [ {targetName:"may_act",function:{custom:({client_id:$cid}|tojson)}}, {targetName:"groups",sourceId:"4"}] else [] end) ' "$MANUAL/app.json" > "$MANUAL/update-app.json"
```

Aplicar la configuración:

```bash
curl --fail --silent --show-error --request PUT --header "@$MANUAL/verify.headers" --data-binary "@$MANUAL/update-app.json" "$TENANT/v1.0/applications/$app_id" > "$MANUAL/updated.json"
```

Descargar la configuración resultante:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications/$app_id" > "$MANUAL/app-$suffix.json"
```

Guardar el ID y la credencial en Vault:

```bash
jq --arg id "$app_id" '{application_id:$id,client_id:.providers.oidc.properties.clientId, client_secret:.providers.oidc.properties.clientSecret}' "$MANUAL/app-$suffix.json" | vault kv put -mount=secrets "chatbot/$suffix" -
```

Repetir la configuración anterior con `suffix=research`. Continuar al paso 4 cuando ambas aplicaciones estén configuradas y sus credenciales guardadas en Vault.

## 4. Crear el cliente STS para OBO

[sts.json](../../verify/config/sts.json) exige actor token, emite JWT RS256 de 600 segundos, no concede entitlements administrativos, y solo acepta `vault:path_access`. El mapping `actor-token.sub` toma el sujeto del actor; añadimos la copia del claim `groups` del usuario.

Descargar el inventario de clientes STS:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-list.json"
```

Mostrar sus nombres e IDs:

```bash
jq '.clients[]|{clientName,clientId}' "$MANUAL/sts-list.json"
```

Preparar el payload con el claim `groups`:

```bash
jq '.clientName="vault-chatbot-sts" | .tokenSettings.introspectMap += [{name:"groups",function:{custom:"requestContext[\"subject_token\"].groups"}}]' verify/config/sts.json > "$MANUAL/sts-payload.json"
```

Revisar el payload:

```bash
cat "$MANUAL/sts-payload.json"
```

Actualizar el inventario y crear el cliente STS únicamente si no existe. **Copiar el bloque completo:** el POST solo se ejecuta cuando la consulta acaba correctamente y no hay ninguna coincidencia. Si el nombre ya existe, se omite la creación.

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-list.json" &&
if jq -e '[.clients[]|select(.clientName=="vault-chatbot-sts")]|length==0' "$MANUAL/sts-list.json" >/dev/null; then
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --dump-header "$MANUAL/sts-response.headers" --data-binary "@$MANUAL/sts-payload.json" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-created.json"
fi
```

La creación puede devolver **HTTP 201 con el cuerpo vacío**; en ese caso el ID está en la cabecera `Location` de `sts-response.headers`. Un `sts-created.json` vacío no justifica repetir el POST: comprobar el inventario.

Obtener su ID por inventario y guardar la credencial:

Actualizar el inventario:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-list.json"
```

Obtener el ID único de `vault-chatbot-sts`:

```bash
STS_ID=$(jq -er '[.clients[]|select(.clientName=="vault-chatbot-sts")|.clientId]| if length==0 then error("STS ausente: revisar la creación") elif length>1 then error("STS duplicado: contrastar los IDs con la credencial de Vault") else .[0] end' "$MANUAL/sts-list.json")
```

Si hay duplicados, mostrar las coincidencias con el comando de inventario anterior. Si Vault ya conserva una credencial válida, obtener el ID que usa con `STS_ID=$(vault kv get -mount=secrets -field=client_id chatbot/sts)` y comprobar que corresponde a una de las coincidencias antes de continuar. Si no hay una credencial previa que identifique el cliente, revisar los duplicados antes de seleccionar uno. No elegir el primero del listado ni repetir el POST. La retirada de un duplicado requiere comprobar antes sus dependencias.

Descargar su configuración:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients/$STS_ID" > "$MANUAL/sts.json"
```

Guardar la credencial en Vault:

```bash
jq --arg id "$STS_ID" '{client_id:$id,client_secret:.clientAuthentication.clientSecret}' "$MANUAL/sts.json" | vault kv put -mount=secrets chatbot/sts -
```

Comprobar las restricciones del cliente:

```bash
jq -e '.enabled and .tokenExchangeSettings.actorTokenRequired and .tokenSettings.accessTokenType=="jwt" and .tokenSettings.restrictEntitlements and (.tokenSettings.entitlements|length==0)' "$MANUAL/sts.json"
```

Resultado esperado: **`true`**. Si devuelve `false` o un error, detenerse y revisar antes de continuar.

Para actualizar un STS existente, hacer GET, mezclar ese documento con `sts-payload.json` usando `jq -s '.[0]*.[1]'` y hacer PUT al mismo ID; no recrear su secreto.

## 5. Crear los tres usuarios de prueba

Las operaciones SCIM usan **Content-Type y Accept `application/scim+json`**. El `Accept: application/json` de las cabeceras administrativas no basta: Verify devuelve HTTP 406 en el PATCH de activación.

Repetir los pasos 5–6 para `ROLE=reader`, `ROLE=writer` y `ROLE=supervisor`. Los bloques siguientes consultan el usuario antes de crearlo y reutilizan su ID si existe. Si la activación quedó pendiente (`pwdReset=true`), completan el cambio de contraseña; si ya estaba completada, lo omiten.

Seleccionar el rol. En la primera pasada se usa `reader`; para las siguientes, ejecutar `ROLE=writer` o `ROLE=supervisor` antes de repetir los pasos 5–6:

```bash
ROLE=${ROLE:-reader}
```

Guardar la credencial del usuario en el archivo privado:

```bash
vault kv get -format=json -mount=secrets "chatbot/users/$ROLE" | jq '.data.data' > "$MANUAL/user-credential.json"
```

Generar una contraseña inicial distinta de la definitiva:

```bash
{ printf 'Lu!9'; openssl rand -hex 18; } > "$MANUAL/initial-password"
```

Preparar el payload del usuario con `pwdReset=true`. Así, si el POST se completa
pero se pierde la respuesta, la siguiente ejecución detecta la activación pendiente
y aplica la contraseña definitiva de Vault. El PATCH posterior elimina esa marca:

```bash
jq --arg role "$ROLE" --rawfile initial "$MANUAL/initial-password" '{ schemas:["urn:ietf:params:scim:schemas:core:2.0:User", "urn:ietf:params:scim:schemas:extension:ibm:2.0:User", "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification"], userName:.username,password:($initial|rtrimstr("\n")),active:true, name:{givenName:"Lumen",familyName:$role,formatted:("Lumen "+$role)},displayName:("Lumen "+$role), emails:[{type:"work",value:(.username+"@example.invalid"),primary:true}], "urn:ietf:params:scim:schemas:extension:ibm:2.0:User":{ userCategory:"regular",realm:"cloudIdentityRealm",pwdReset:true}, "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"} }' "$MANUAL/user-credential.json" > "$MANUAL/create-user.json"
```

Consultar el usuario y crearlo solo si falta. **Copiar el bloque completo.** `created_user` indica si esta pasada acaba de crearlo:

```bash
created_user=false
username=$(jq -er '.userName|select(type=="string" and length>0)' "$MANUAL/create-user.json") &&
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' --get --data-urlencode "filter=userName eq \"$username\"" "$TENANT/v2.0/Users" > "$MANUAL/users-list.json" &&
USER_ID=$(jq -r --arg name "$username" '[.Resources[]|select(.userName==$name)]|if length>1 then error("Usuario duplicado") else .[0].id//empty end' "$MANUAL/users-list.json") &&
if [ -z "$USER_ID" ]; then
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --header 'Content-Type: application/scim+json' --header 'Accept: application/scim+json' --data-binary "@$MANUAL/create-user.json" "$TENANT/v2.0/Users" > "$MANUAL/user.json" && created_user=true
else
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' "$TENANT/v2.0/Users/$USER_ID" > "$MANUAL/user.json"
fi
```

Continuar solo si el bloque ha terminado correctamente. Si un POST anterior devolvió **409**, volver a ejecutar este bloque de consulta y reutilización; no repetir el POST aislado. Un `user.json` vacío o conservado de otra pasada no confirma el resultado del intento actual.

Obtener su ID, comprobando que la respuesta corresponde a la credencial del usuario actual:

```bash
USER_ID=$(jq -er --slurpfile credential "$MANUAL/user-credential.json" 'if .userName==$credential[0].username and (.id|type)=="string" and (.id|length)>0 then .id else error("Respuesta de otro usuario o sin ID válido") end' "$MANUAL/user.json")
```

Guardar el ID junto con la credencial en Vault. El JSON se prepara primero en un archivo privado; `&&` ejecuta la escritura solo si la credencial es válida y corresponde a `ROLE`:

```bash
jq -es --arg id "${USER_ID:?Obtén primero un USER_ID válido}" --arg role "$ROLE" 'if length==1 and .[0].username==("lumen-"+$role) and (.[0].password|type)=="string" then .[0]+{user_id:$id} else error("Credencial ausente o de otro usuario") end' "$MANUAL/user-credential.json" > "$MANUAL/user-credential-with-id.json" && vault kv put -mount=secrets "chatbot/users/$ROLE" - < "$MANUAL/user-credential-with-id.json"
```

Verify puede exigir cambiar la contraseña inicial. Instalar la contraseña definitiva de `.env` mediante PATCH con el permiso administrativo `manageUsersPwdReset`. Se usa una inicial distinta para no activar la prohibición de reutilización:

Preparar el cambio de contraseña:

```bash
jq '{schemas:["urn:ietf:params:scim:api:messages:2.0:PatchOp"],Operations:[ {op:"replace",path:"password",value:.password}, {op:"add",path:"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification:notifyType",value:"NONE"} ]}' "$MANUAL/user-credential.json" > "$MANUAL/activate-user.json"
```

Aplicar el cambio solo al usuario recién creado o cuando Verify indica que la activación está pendiente. **Copiar el condicional completo:**

```bash
if [ "${created_user:-false}" = true ] || jq -e '.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset==true' "$MANUAL/user.json" >/dev/null; then
  curl --fail --silent --show-error --request PATCH --header "@$MANUAL/verify.headers" --header 'Content-Type: application/scim+json' --header 'Accept: application/scim+json' --header 'usershouldnotneedtoresetpassword: true' --data-binary "@$MANUAL/activate-user.json" "$TENANT/v2.0/Users/$USER_ID" > "$MANUAL/activated.json"
  created_user=false
fi
```

Descargar el usuario para comprobar su estado:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' "$TENANT/v2.0/Users/$USER_ID" > "$MANUAL/user-check.json"
```

Comprobar que está activo y no requiere cambiar la contraseña:

```bash
jq -e '.active and (.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset!=true)' "$MANUAL/user-check.json"
```

Resultado esperado: **`true`**. Si devuelve `false` o un error, detenerse y revisar antes de continuar.

## 6. Crear el grupo y añadir su usuario

Para el mismo `ROLE` y `USER_ID` del paso anterior:

Construir el nombre del grupo:

```bash
GROUP="chatbot-${ROLE}s"
```

Preparar el grupo con el usuario como miembro:

```bash
jq -n --arg group "$GROUP" --arg uid "$USER_ID" '{ schemas:["urn:ietf:params:scim:schemas:core:2.0:Group", "urn:ietf:params:scim:schemas:extension:ibm:2.0:Group", "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification"], displayName:$group,members:[{value:$uid,type:"user"}], "urn:ietf:params:scim:schemas:extension:ibm:2.0:Group":{groupType:"standard"}, "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"} }' > "$MANUAL/create-group.json"
```

Consultar el grupo y crearlo solo si falta. Si existe, añadir el usuario únicamente cuando todavía no es miembro. **Copiar el bloque completo:**

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' --get --data-urlencode "filter=displayName eq \"$GROUP\"" "$TENANT/v2.0/Groups" > "$MANUAL/groups-list.json" &&
GROUP_ID=$(jq -r --arg name "$GROUP" '[.Resources[]|select(.displayName==$name)]|if length>1 then error("Grupo duplicado") else .[0].id//empty end' "$MANUAL/groups-list.json") &&
if [ -z "$GROUP_ID" ]; then
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --header 'Content-Type: application/scim+json' --header 'Accept: application/scim+json' --data-binary "@$MANUAL/create-group.json" "$TENANT/v2.0/Groups" > "$MANUAL/group-$ROLE.json"
else
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' "$TENANT/v2.0/Groups/$GROUP_ID" > "$MANUAL/group-$ROLE.json"
  if ! jq -e --arg uid "$USER_ID" 'any(.members[]?;.value==$uid)' "$MANUAL/group-$ROLE.json" >/dev/null; then
    jq -n --arg uid "$USER_ID" '{schemas:["urn:ietf:params:scim:api:messages:2.0:PatchOp"],Operations:[{op:"add",path:"members",value:[{value:$uid,type:"user"}]}],"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"}}' > "$MANUAL/patch-group.json"
    curl --fail --silent --show-error --request PATCH --header "@$MANUAL/verify.headers" --header 'Content-Type: application/scim+json' --header 'Accept: application/scim+json' --data-binary "@$MANUAL/patch-group.json" "$TENANT/v2.0/Groups/$GROUP_ID" > "$MANUAL/patched-group.json"
    curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' "$TENANT/v2.0/Groups/$GROUP_ID" > "$MANUAL/group-$ROLE.json"
  fi
fi
```

Mostrar el ID, el nombre y los miembros:

```bash
jq '{id,displayName,members}' "$MANUAL/group-$ROLE.json"
```

El archivo `group-$ROLE.json` conserva el ID y los miembros del grupo creado o reutilizado. **Volver al paso 5 para writer y supervisor**. El capítulo 04 asigna estos tres grupos a la aplicación y a políticas de Vault.

## 7. Guardar el inventario de usuarios en Vault

El aprovisionamiento también conserva el inventario no secreto en `chatbot/directory`. Después de crear los tres usuarios y grupos:

Inicializar el inventario local:

```bash
printf '[]' > "$MANUAL/directory.json"
```

Añadir los tres usuarios y grupos. **Copiar este bucle completo, desde `for` hasta `done`:**

```bash
for role in reader writer supervisor; do
  vault kv get -format=json -mount=secrets "chatbot/users/$role" | jq '.data.data' > "$MANUAL/directory-user.json"
  jq --arg role "$role" --slurpfile user "$MANUAL/directory-user.json" --slurpfile group "$MANUAL/group-$role.json" '.+[{username:$user[0].username, user_id:$user[0].user_id,group:("chatbot-"+$role+"s"),group_id:$group[0].id, password_reset_required:false}]' "$MANUAL/directory.json" > "$MANUAL/next.json"
  mv "$MANUAL/next.json" "$MANUAL/directory.json"
done
```

Guardar el inventario en Vault:

```bash
jq '{users:.}' "$MANUAL/directory.json" | vault kv put -mount=secrets chatbot/directory -
```

Si reutilizaste usuarios/grupos existentes, guardar previamente sus IDs reales en los archivos y secretos de los pasos 5–6; no asumir que coinciden con una instalación anterior. `password_reset_required:false` refleja la comprobación del paso 5, que debe haber pasado para las tres cuentas.

La aplicación usa **Authorization Code + PKCE**, ROPC desactivado y ningún refresh token; son decisiones de este workspace que difieren de ciertos ejemplos simplificados. [Guía oficial Verify/Vault](https://developer.hashicorp.com/vault/ai/iam/providers/verify).

Fuentes locales: [configure-base.sh](../../verify/scripts/configure-base.sh), [02-verify-apps.sh](../../chatbot/scripts/02-verify-apps.sh), [03-verify-users.sh](../../chatbot/scripts/03-verify-users.sh).
