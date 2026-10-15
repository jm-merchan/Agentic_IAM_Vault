#!/usr/bin/env bash
# Requires manageUserStandardGroups on vault-verify-automation.
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
admin_login
scim() { api "$@" --header 'Accept: application/scim+json' --header 'Content-Type: application/scim+json'; }
printf '[]' > "$TMP_WORK/users-public.json"
for role in reader writer supervisor; do
  created_user=false
  username="lumen-$role"
  scim GET /v2.0/Users "$TMP_WORK/users.json" --get --data-urlencode "filter=userName eq \"$username\""
  uid=$(jq -r '.Resources|if length>1 then error("Duplicate user") else .[0].id//empty end' "$TMP_WORK/users.json")
  if [ -z "$uid" ]; then
    if ! vault kv metadata get -mount=secrets "chatbot/users/$role" >/dev/null 2>&1; then
      { printf 'Lu!7'; openssl rand -hex 18; } > "$TMP_WORK/password"
      jq -n --arg username "$username" --rawfile password "$TMP_WORK/password" '{username:$username,password:($password|rtrimstr("\n")),provider:"Cloud Directory"}' | kv_write "chatbot/users/$role"
    fi
    kv_read "chatbot/users/$role" > "$TMP_WORK/credential.json"
    # Use a disposable initial password; the activation PATCH installs the
    # intended credential from Vault/.env without triggering password reuse.
    { printf 'Lu!9'; openssl rand -hex 18; } > "$TMP_WORK/initial-password"
    jq --arg role "$role" '{schemas:["urn:ietf:params:scim:schemas:core:2.0:User","urn:ietf:params:scim:schemas:extension:ibm:2.0:User","urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification"],userName:.username,password:.password,name:{givenName:"Lumen",familyName:$role,formatted:("Lumen "+$role)},displayName:("Lumen "+$role),active:true,emails:[{type:"work",value:(.username+"@example.invalid"),primary:true}],"urn:ietf:params:scim:schemas:extension:ibm:2.0:User":{userCategory:"regular",realm:"cloudIdentityRealm",pwdReset:false},"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"}}' "$TMP_WORK/credential.json" > "$TMP_WORK/create-user.json"
    jq --rawfile password "$TMP_WORK/initial-password" '.password=($password|rtrimstr("\n"))' "$TMP_WORK/create-user.json" > "$TMP_WORK/create-initial.json"
    scim POST /v2.0/Users "$TMP_WORK/user.json" --data-binary "@$TMP_WORK/create-initial.json"
    uid=$(jq -er .id "$TMP_WORK/user.json")
    created_user=true
    jq --arg id "$uid" '.+{user_id:$id}' "$TMP_WORK/credential.json" | kv_write "chatbot/users/$role"
  fi
  scim GET "/v2.0/Users/$uid" "$TMP_WORK/user.json"
  if [ "$created_user" = true ] || jq -e '.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset==true' "$TMP_WORK/user.json" >/dev/null; then
    # IBM uses this header on password updates; pwdReset in a PUT is ignored.
    kv_read "chatbot/users/$role" > "$TMP_WORK/credential.json"
    jq -jr .password "$TMP_WORK/credential.json" > "$TMP_WORK/password"
    jq -n --rawfile password "$TMP_WORK/password" '{schemas:["urn:ietf:params:scim:api:messages:2.0:PatchOp"],Operations:[{op:"replace",path:"password",value:($password|rtrimstr("\n"))},{op:"add",path:"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification:notifyType",value:"NONE"}]}' > "$TMP_WORK/activate.json"
    scim PATCH "/v2.0/Users/$uid" "$TMP_WORK/activated.json" --header 'usershouldnotneedtoresetpassword: true' --data-binary "@$TMP_WORK/activate.json"
    jq --rawfile password "$TMP_WORK/password" '.password=($password|rtrimstr("\n"))' "$TMP_WORK/credential.json" | kv_write "chatbot/users/$role"
    for attempt in 1 2 3 4 5; do
      scim GET "/v2.0/Users/$uid" "$TMP_WORK/user.json"
      if jq -e '.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset!=true' "$TMP_WORK/user.json" >/dev/null; then break; fi
      sleep 1
    done
    jq -e '.["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset!=true' "$TMP_WORK/user.json" >/dev/null || fail 'Verify still requires a password change.'
  fi
  group="chatbot-${role}s"
  scim GET /v2.0/Groups "$TMP_WORK/groups.json" --get --data-urlencode "filter=displayName eq \"$group\""
  gid=$(jq -r '.Resources|if length>1 then error("Duplicate group") else .[0].id//empty end' "$TMP_WORK/groups.json")
  if [ -z "$gid" ]; then
    jq -n --arg group "$group" --arg uid "$uid" '{schemas:["urn:ietf:params:scim:schemas:core:2.0:Group","urn:ietf:params:scim:schemas:extension:ibm:2.0:Group","urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification"],displayName:$group,members:[{value:$uid,type:"user"}],"urn:ietf:params:scim:schemas:extension:ibm:2.0:Group":{groupType:"standard"},"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"}}' > "$TMP_WORK/create-group.json"
    scim POST /v2.0/Groups "$TMP_WORK/group.json" --data-binary "@$TMP_WORK/create-group.json"
    gid=$(jq -er .id "$TMP_WORK/group.json")
  else
    scim GET "/v2.0/Groups/$gid" "$TMP_WORK/group.json"
    if ! jq -e --arg uid "$uid" 'any(.members[]?;.value==$uid)' "$TMP_WORK/group.json" >/dev/null; then
      jq -n --arg uid "$uid" '{schemas:["urn:ietf:params:scim:api:messages:2.0:PatchOp"],Operations:[{op:"add",path:"members",value:[{value:$uid,type:"user"}]}],"urn:ietf:params:scim:schemas:extension:ibm:2.0:Notification":{notifyType:"NONE"}}' > "$TMP_WORK/patch-group.json"
      scim PATCH "/v2.0/Groups/$gid" "$TMP_WORK/patched.json" --data-binary "@$TMP_WORK/patch-group.json"
    fi
  fi
  jq --arg username "$username" --arg uid "$uid" --arg group "$group" --arg gid "$gid" --slurpfile u "$TMP_WORK/user.json" '.+[{username:$username,user_id:$uid,group:$group,group_id:$gid,password_reset_required:($u[0]["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].pwdReset//false)}]' "$TMP_WORK/users-public.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/users-public.json"
  printf 'Configured %s in %s; credential kept in verify/secrets/chatbot/users/%s.\n' "$username" "$group" "$role"
done
cp "$TMP_WORK/users-public.json" "$CHATBOT_DIR/docs/users.json"
cat "$TMP_WORK/users-public.json" | jq '{users:.}' | kv_write chatbot/directory
