# 03 · Applications, RAR, STS and users in IBM Verify

[Index](README.md) · Requires [01](01-vault.md) · Next: [Vault IAM](04-vault-iam.md)

**To run and resume this chapter**, use `bash scripts/manual/paso-a-paso.sh desde verify-base`. The [guided walkthrough](PASO-A-PASO.md) splits RAR, OIDC, research, STS and users into executable steps, loads the environment and renews the token in each one. The blocks below remain as a detailed reference of the operations.

Run each block separately in the same **Bash** session, from the project root. Copy only its content and wait for the `bash-3.2$` prompt (or equivalent) to return before pasting the next one. Simple commands take a single line, even if the viewer wraps them to the window width.

If after pasting a complete block the terminal still shows `>`, press **Ctrl+C** to cancel the pending input and copy that block again. Do not paste the next one or try to close a quote by hand. The `if … fi` conditionals and the `for … done` loop are copied whole; while Bash receives them it may show `>`.

If an error terminates Bash and the zsh prompt (`❯`) reappears, first run `bash` and then the three session-loading blocks from step 1. Also restore the variables of the interrupted step, such as `ROLE=reader`. Variables from the previous Bash session are not recovered in the parent shell. Reload the view of this file if it still shows simple commands split with `\` at the end of the line.

<a id="1-obtener-un-token-administrativo"></a>
## 1. Obtain an administrative token

Load the chapter 00 session from Bash:

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
```

Load the Vault connection:

```bash
source "$LUMEN_STATE_DIR/vault/config.env"
```

Select the `verify` namespace:

```bash
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

Save the administrative credential to the private file:

```bash
vault kv get -format=json -mount=secrets verify-admin | jq '.data.data' > "$MANUAL/verify-admin.json"
```

Prepare the headers to request the token:

```bash
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+ "\nContent-Type: application/x-www-form-urlencoded\n"' "$MANUAL/verify-admin.json" > "$MANUAL/verify-basic.headers"
```

Request the administrative token:

```bash
curl --fail --silent --show-error "$TENANT/oauth2/token" --header "@$MANUAL/verify-basic.headers" --data 'grant_type=client_credentials' > "$MANUAL/verify-admin-token.json"
```

Prepare the headers for the following calls to Verify:

```bash
jq -jer '"Authorization: Bearer "+.access_token+ "\nContent-Type: application/json\nAccept: application/json\n"' "$MANUAL/verify-admin-token.json" > "$MANUAL/verify.headers"
```

Repeat this step if the administration token expires. `curl --fail` stops the block when it receives an HTTP error; do not continue from an empty JSON. Responses containing secrets are saved to files, without printing them.

If a script reports `/tmp/vault/config.env: No such file or directory`, update
`session.sh` with the session-creation block from [00](00-entorno.md#3-create-a-reusable-working-session)
and load it again. It must export `VAULT_ENV_FILE` pointing to
`$LUMEN_STATE_DIR/vault/config.env`, where chapter 01 saved the connection.
Do not copy old keys to `/tmp/vault` or initialize Vault again.

## 2. Register the RAR type `vault:path_access`

[rar-schema.json](../../verify/config/rar-schema.json) requires `type`, `path` and `capabilities`; it allows `read/create/update/delete/sudo/list/deny` and the optional properties `allowed_parameters`, `denied_parameters` and `required_parameters`. It rejects other properties. Earlier tokens without parameters remain valid. Inspect the inventory first:

Download the inventory of RAR types:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/auth-detail-types" > "$MANUAL/rar-list.json"
```

Show the `vault:path_access` matches:

```bash
jq '[..|objects|select(.type?=="vault:path_access")|{id,type}]|unique' "$MANUAL/rar-list.json"
```

Review the local schema:

```bash
cat verify/config/rar-schema.json
```

The following steps create the type only when the previous inventory does not contain it. If it exists, they keep its ID. The reconciler only extends Lumen's known previous schema with the three optional fields; any other difference is treated as a conflict. It keeps the description, consent and other settings of the existing type.

Get the existing ID. If there is more than one, the command fails:

```bash
RAR_ID=$(jq -r '[..|objects|select(.type?=="vault:path_access")|.id]|unique| if length>1 then error("Duplicate RAR") else .[0]//empty end' "$MANUAL/rar-list.json")
```

Create the type only if it is missing. **Copy this whole conditional, from `if` to `fi`, and wait for the prompt to return:**

```bash
if [ -z "$RAR_ID" ]; then
  jq -n --rawfile schema verify/config/rar-schema.json '{ type:"vault:path_access",description:"Vault path and capabilities for delegated access", schema:$schema,inlineMode:true, consentInlineText:("<div>Permitir al agente las operaciones solicitadas en Vault.</div>"|@base64) }' > "$MANUAL/rar-create.json"
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --data-binary "@$MANUAL/rar-create.json" "$TENANT/v1.0/auth-detail-types" > "$MANUAL/rar-created.json"
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/auth-detail-types" > "$MANUAL/rar-list.json"
fi
```

Confirm that exactly one ID exists:

```bash
RAR_ID=$(jq -er '[..|objects|select(.type?=="vault:path_access")|.id]|unique| if length==1 then .[0] else error("Duplicate or missing RAR") end' "$MANUAL/rar-list.json")
```

Reconcile the known schema and download its configuration. The script obtains a new administrative token and does not modify OAuth clients or Vault policies:

```bash
bash verify/scripts/configure-rar.sh
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/auth-detail-types/$RAR_ID" > "$MANUAL/rar-check.json"
```

Compare the Verify schema with the local file:

```bash
jq -e --slurpfile schema verify/config/rar-schema.json '(.schema|fromjson)==$schema[0]' "$MANUAL/rar-check.json"
```

Expected result: **`true`**. If it returns `false` or an error, stop and review before continuing.

<a id="3-crear-las-aplicaciones-oidc-y-de-investigación"></a>
## 3. Create the OIDC and research applications

The [OIDC template](../../verify/config/oidc-template.json) is the Verify application payload (`templateId=998`). The strings `"true"`/`"false"` are used in the API fields that require them.

| App | Grant | Usage |
|---|---|---|
| `vault-chatbot-oidc` | Authorization Code + PKCE and Client Credentials | Human login and OBO actor |
| `vault-chatbot-research` | Client Credentials | Autonomous agent that retrieves Tavily |
| `vault-chatbot-xai` / `vault-chatbot-openai` | Client Credentials + RAR | Created in their own chapters |

Download the application inventory:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
```

Show their names and links:

```bash
jq '[._embedded.applications[]|{name,url:._links.self.href}]' "$MANUAL/apps.json"
```

Review the local template:

```bash
cat verify/config/oidc-template.json
```

The following steps configure one application per pass: first `oidc` and then `research`. An app with the exact name is reused, or created if it is absent. First its client ID is obtained; then `may_act.client_id` is configured in the human tokens. The `groups` claim uses the Verify attribute `sourceId=4` of the reference tenant; check that it maps to groups if you adapt this to another tenant.

Select the application. The first pass uses `oidc`; for the second one, run `suffix=research` before repeating these steps:

```bash
suffix=${suffix:-oidc}
```

Build the application name:

```bash
name="vault-chatbot-$suffix"
```

Refresh the inventory:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
```

Look up the ID by exact name. If there are duplicates, the command fails:

```bash
app_id=$(jq -r --arg name "$name" '[._embedded.applications[]|select(.name==$name)| ._links.self.href|split("/")[-1]]| if length>1 then error("Duplicate name") else .[0]//empty end' "$MANUAL/apps.json")
```

Create the application only if it is missing. **Copy this whole conditional, from `if` to `fi`:**

```bash
if [ -z "$app_id" ]; then
  jq --arg name "$name" '.+{name:$name,description:"Vault IAM chatbot laboratory"}' verify/config/oidc-template.json > "$MANUAL/create-app.json"
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --data-binary "@$MANUAL/create-app.json" "$TENANT/v1.0/applications" > "$MANUAL/created.json"
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications" > "$MANUAL/apps.json"
  app_id=$(jq -er --arg name "$name" '._embedded.applications[]|select(.name==$name)| ._links.self.href|split("/")[-1]' "$MANUAL/apps.json")
fi
```

Download the application configuration:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications/$app_id" > "$MANUAL/app.json"
```

Get its client ID:

```bash
cid=$(jq -er .providers.oidc.properties.clientId "$MANUAL/app.json")
```

Prepare the OIDC configuration and the claims:

```bash
jq --arg cid "$cid" --arg suffix "$suffix" ' .providers.oidc.applicationUrl="http://localhost:8088" | .providers.oidc.properties.redirectUris=["http://localhost:8088/auth/callback"] | .providers.oidc.properties.grantTypes.ropc="false" | .providers.oidc.properties.grantTypes.authorizationCode=(if $suffix=="oidc" then "true" else "false" end) | .providers.oidc.properties.grantTypes.clientCredentials="true" | .providers.oidc.properties.generateRefreshToken="false" | .providers.oidc.properties.accessTokenExpiry=600 | .providers.oidc.token.accessTokenType="jwt" | .providers.oidc.requirePkceVerification="true" | .providers.oidc.token.attributeMappings=(if $suffix=="oidc" then [ {targetName:"may_act",function:{custom:({client_id:$cid}|tojson)}}, {targetName:"groups",sourceId:"4"}] else [] end) ' "$MANUAL/app.json" > "$MANUAL/update-app.json"
```

Apply the configuration:

```bash
curl --fail --silent --show-error --request PUT --header "@$MANUAL/verify.headers" --data-binary "@$MANUAL/update-app.json" "$TENANT/v1.0/applications/$app_id" > "$MANUAL/updated.json"
```

Download the resulting configuration:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/applications/$app_id" > "$MANUAL/app-$suffix.json"
```

Save the ID and the credential in Vault:

```bash
jq --arg id "$app_id" '{application_id:$id,client_id:.providers.oidc.properties.clientId, client_secret:.providers.oidc.properties.clientSecret}' "$MANUAL/app-$suffix.json" | vault kv put -mount=secrets "chatbot/$suffix" -
```

Repeat the configuration above with `suffix=research`. Continue to step 4 once both applications are configured and their credentials saved in Vault.

## 4. Create the STS client for OBO

[sts.json](../../verify/config/sts.json) requires an actor token, issues 600-second RS256 JWTs, grants no administrative entitlements, and only accepts `vault:path_access`. The `actor-token.sub` mapping takes the actor's subject; we add a copy of the user's `groups` claim.

Download the inventory of STS clients:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-list.json"
```

Show their names and IDs:

```bash
jq '.clients[]|{clientName,clientId}' "$MANUAL/sts-list.json"
```

Prepare the payload with the `groups` claim:

```bash
jq '.clientName="vault-chatbot-sts" | .tokenSettings.introspectMap += [{name:"groups",function:{custom:"requestContext[\"subject_token\"].groups"}}]' verify/config/sts.json > "$MANUAL/sts-payload.json"
```

Review the payload:

```bash
cat "$MANUAL/sts-payload.json"
```

Refresh the inventory and create the STS client only if it does not exist. **Copy the whole block:** the POST only runs when the query finishes successfully and there is no match. If the name already exists, creation is skipped.

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-list.json" &&
if jq -e '[.clients[]|select(.clientName=="vault-chatbot-sts")]|length==0' "$MANUAL/sts-list.json" >/dev/null; then
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --dump-header "$MANUAL/sts-response.headers" --data-binary "@$MANUAL/sts-payload.json" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-created.json"
fi
```

Creation may return **HTTP 201 with an empty body**; in that case the ID is in the `Location` header of `sts-response.headers`. An empty `sts-created.json` does not justify repeating the POST: check the inventory.

Get its ID from the inventory and save the credential:

Refresh the inventory:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients" > "$MANUAL/sts-list.json"
```

Get the unique ID of `vault-chatbot-sts`:

```bash
STS_ID=$(jq -er '[.clients[]|select(.clientName=="vault-chatbot-sts")|.clientId]| if length==0 then error("STS missing: review the creation") elif length>1 then error("Duplicate STS: compare the IDs with the Vault credential") else .[0] end' "$MANUAL/sts-list.json")
```

If there are duplicates, show the matches with the previous inventory command. If Vault already holds a valid credential, get the ID it uses with `STS_ID=$(vault kv get -mount=secrets -field=client_id chatbot/sts)` and check that it corresponds to one of the matches before continuing. If there is no previous credential that identifies the client, review the duplicates before selecting one. Do not pick the first one in the list or repeat the POST. Removing a duplicate requires checking its dependencies first.

Download its configuration:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" "$TENANT/v1.0/sts/oauth/clients/$STS_ID" > "$MANUAL/sts.json"
```

Save the credential in Vault:

```bash
jq --arg id "$STS_ID" '{client_id:$id,client_secret:.clientAuthentication.clientSecret}' "$MANUAL/sts.json" | vault kv put -mount=secrets chatbot/sts -
```

Check the client restrictions:

```bash
jq -e '.enabled and .tokenExchangeSettings.actorTokenRequired and .tokenSettings.accessTokenType=="jwt" and .tokenSettings.restrictEntitlements and (.tokenSettings.entitlements|length==0)' "$MANUAL/sts.json"
```

Expected result: **`true`**. If it returns `false` or an error, stop and review before continuing.

To update an existing STS, do a GET, merge that document with `sts-payload.json` using `jq -s '.[0]*.[1]'` and do a PUT to the same ID; do not recreate its secret.

<a id="5-crear-los-tres-usuarios-de-prueba"></a>
## 5. Create the three test users

SCIM operations use **Content-Type and Accept `application/scim+json`**. The `Accept: application/json` of the administrative headers is not enough: Verify returns HTTP 406 on the activation PATCH.

Repeat steps 5–6 for `ROLE=reader`, `ROLE=writer` and `ROLE=supervisor`. The following blocks look up the user before creating it and reuse its ID if it exists. If activation was left pending (`pwdReset=true`), they complete the password change; if it was already completed, they skip it.

Select the role. The first pass uses `reader`; for the following ones, run `ROLE=writer` or `ROLE=supervisor` before repeating steps 5–6:

```bash
ROLE=${ROLE:-reader}
```

Save the user's credential to the private file:

```bash
vault kv get -format=json -mount=secrets "chatbot/users/$ROLE" | jq '.data.data' > "$MANUAL/user-credential.json"
```

Generate an initial password different from the final one:

```bash
{ printf 'Lu!9'; openssl rand -hex 18; } > "$MANUAL/initial-password"
```

Prepare the user payload with `pwdReset=true`. That way, if the POST completes
but the response is lost, the next run detects the pending activation
and applies the final password from Vault. The later PATCH removes that flag:

```bash
jq --arg role "$ROLE" --rawfile initial "$MANUAL/initial-password" '{ schemas:["urn:ietf:params:scim:schemas:core:2.0:User", "urn:ietf:params:scim:schemas:extension:ibm:2.0:User", "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification"], userName:.username,password:($initial|rtrimstr("\n")),active:true, name:{givenName:"Lumen",familyName:$role,formatted:("Lumen "+$role)},displayName:("Lumen "+$role), emails:[{type:"work",value:(.username+"@example.invalid"),primary:true}], "urn:ietf:params:scim:schemas:extension:ibm:2.0:User":{ userCategory:"regular",realm:"cloudIdentityRealm",pwdReset:true}, "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"} }' "$MANUAL/user-credential.json" > "$MANUAL/create-user.json"
```

Look up the user and create it only if it is missing. **Copy the whole block.** `created_user` indicates whether this pass has just created it:

```bash
created_user=false
username=$(jq -er '.userName|select(type=="string" and length>0)' "$MANUAL/create-user.json") &&
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' --get --data-urlencode "filter=userName eq \"$username\"" "$TENANT/v2.0/Users" > "$MANUAL/users-list.json" &&
USER_ID=$(jq -r --arg name "$username" '[.Resources[]|select(.userName==$name)]|if length>1 then error("Duplicate user") else .[0].id//empty end' "$MANUAL/users-list.json") &&
if [ -z "$USER_ID" ]; then
  curl --fail --silent --show-error --request POST --header "@$MANUAL/verify.headers" --header 'Content-Type: application/scim+json' --header 'Accept: application/scim+json' --data-binary "@$MANUAL/create-user.json" "$TENANT/v2.0/Users" > "$MANUAL/user.json" && created_user=true
else
  curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' "$TENANT/v2.0/Users/$USER_ID" > "$MANUAL/user.json"
fi
```

Continue only if the block has finished successfully. If a previous POST returned **409**, run this lookup-and-reuse block again; do not repeat the isolated POST. An empty `user.json`, or one kept from another pass, does not confirm the result of the current attempt.

Get its ID, checking that the response corresponds to the current user's credential:

```bash
USER_ID=$(jq -er --slurpfile credential "$MANUAL/user-credential.json" 'if .userName==$credential[0].username and (.id|type)=="string" and (.id|length)>0 then .id else error("Response for another user or without a valid ID") end' "$MANUAL/user.json")
```

Save the ID together with the credential in Vault. The JSON is first prepared in a private file; `&&` runs the write only if the credential is valid and corresponds to `ROLE`:

```bash
jq -es --arg id "${USER_ID:?Obtain a valid USER_ID first}" --arg role "$ROLE" 'if length==1 and .[0].username==("lumen-"+$role) and (.[0].password|type)=="string" then .[0]+{user_id:$id} else error("Credential missing or for another user") end' "$MANUAL/user-credential.json" > "$MANUAL/user-credential-with-id.json" && vault kv put -mount=secrets "chatbot/users/$ROLE" - < "$MANUAL/user-credential-with-id.json"
```

Verify may require changing the initial password. Install the final password from `.env` through a PATCH with the administrative permission `manageUsersPwdReset`. A different initial password is used so as not to trigger the reuse prohibition:

Prepare the password change:

```bash
jq '{schemas:["urn:ietf:params:scim:api:messages:2.0:PatchOp"],Operations:[ {op:"replace",path:"password",value:.password}, {op:"add",path:"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification:notifyType",value:"NONE"} ]}' "$MANUAL/user-credential.json" > "$MANUAL/activate-user.json"
```

Apply the change only to a newly created user or when Verify indicates that activation is pending. **Copy the whole conditional:**

```bash
if [ "${created_user:-false}" = true ] || jq -e '.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset==true' "$MANUAL/user.json" >/dev/null; then
  curl --fail --silent --show-error --request PATCH --header "@$MANUAL/verify.headers" --header 'Content-Type: application/scim+json' --header 'Accept: application/scim+json' --header 'usershouldnotneedtoresetpassword: true' --data-binary "@$MANUAL/activate-user.json" "$TENANT/v2.0/Users/$USER_ID" > "$MANUAL/activated.json"
  created_user=false
fi
```

Download the user to check its status:

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' "$TENANT/v2.0/Users/$USER_ID" > "$MANUAL/user-check.json"
```

Check that it is active and does not require a password change:

```bash
jq -e '.active and (.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset!=true)' "$MANUAL/user-check.json"
```

Expected result: **`true`**. If it returns `false` or an error, stop and review before continuing.

## 6. Create the group and add its user

For the same `ROLE` and `USER_ID` from the previous step:

Build the group name:

```bash
GROUP="chatbot-${ROLE}s"
```

Prepare the group with the user as a member:

```bash
jq -n --arg group "$GROUP" --arg uid "$USER_ID" '{ schemas:["urn:ietf:params:scim:schemas:core:2.0:Group", "urn:ietf:params:scim:schemas:extension:ibm:2.0:Group", "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification"], displayName:$group,members:[{value:$uid,type:"user"}], "urn:ietf:params:scim:schemas:extension:ibm:2.0:Group":{groupType:"standard"}, "urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"} }' > "$MANUAL/create-group.json"
```

Look up the group and create it only if it is missing. If it exists, add the user only when it is not a member yet. **Copy the whole block:**

```bash
curl --fail --silent --show-error --header "@$MANUAL/verify.headers" --header 'Accept: application/scim+json' --get --data-urlencode "filter=displayName eq \"$GROUP\"" "$TENANT/v2.0/Groups" > "$MANUAL/groups-list.json" &&
GROUP_ID=$(jq -r --arg name "$GROUP" '[.Resources[]|select(.displayName==$name)]|if length>1 then error("Duplicate group") else .[0].id//empty end' "$MANUAL/groups-list.json") &&
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

Show the ID, the name and the members:

```bash
jq '{id,displayName,members}' "$MANUAL/group-$ROLE.json"
```

The `group-$ROLE.json` file keeps the ID and members of the created or reused group. **Go back to step 5 for writer and supervisor**. Chapter 04 assigns these three groups to the application and to Vault policies.

## 7. Save the user inventory in Vault

Provisioning also keeps the non-secret inventory in `chatbot/directory`. After creating the three users and groups:

Initialize the local inventory:

```bash
printf '[]' > "$MANUAL/directory.json"
```

Add the three users and groups. **Copy this whole loop, from `for` to `done`:**

```bash
for role in reader writer supervisor; do
  vault kv get -format=json -mount=secrets "chatbot/users/$role" | jq '.data.data' > "$MANUAL/directory-user.json"
  jq --arg role "$role" --slurpfile user "$MANUAL/directory-user.json" --slurpfile group "$MANUAL/group-$role.json" '.+[{username:$user[0].username, user_id:$user[0].user_id,group:("chatbot-"+$role+"s"),group_id:$group[0].id, password_reset_required:false}]' "$MANUAL/directory.json" > "$MANUAL/next.json"
  mv "$MANUAL/next.json" "$MANUAL/directory.json"
done
```

Save the inventory in Vault:

```bash
jq '{users:.}' "$MANUAL/directory.json" | vault kv put -mount=secrets chatbot/directory -
```

If you reused existing users/groups, first save their real IDs in the files and secrets of steps 5–6; do not assume they match a previous installation. `password_reset_required:false` reflects the check in step 5, which must have passed for all three accounts.

The application uses **Authorization Code + PKCE**, ROPC disabled and no refresh token; these are decisions of this workspace that differ from certain simplified examples. [Official Verify/Vault guide](https://developer.hashicorp.com/vault/ai/iam/providers/verify).

Local sources: [configure-base.sh](../../verify/scripts/configure-base.sh), [02-verify-apps.sh](../../chatbot/scripts/02-verify-apps.sh), [03-verify-users.sh](../../chatbot/scripts/03-verify-users.sh).
