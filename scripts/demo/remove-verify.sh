#!/usr/bin/env bash
# Sourced by remove.sh. Authenticate from .env, including when Vault is gone.
# Responses stay in REMOVE_WORK (0700); only names/IDs reach the plan.
remove_api() {
  local method=$1 path=$2 out=$3; shift 3
  local accept=application/json
  local retry_args=(--retry 0)
  # Inventory/detail GETs are safe to retry after a transient timeout. Mutations
  # retain a single attempt: their outcome must be inspected before repeating.
  if [ "$method" = GET ]; then
    retry_args=(--max-time 30 --retry 2 --retry-all-errors --retry-delay 2 --retry-max-time 95)
  fi
  [[ "$path" != /v2.0/* ]] || accept=application/scim+json
  REMOVE_HTTP_STATUS=$(curl --silent --show-error --connect-timeout 15 --max-time 90 \
    --request "$method" --header "@$REMOVE_WORK/verify.headers" --header "Accept: $accept" \
    --output "$out" --write-out '%{http_code}' "${retry_args[@]}" "$VERIFY_TENANT$path" "$@") || fail "Red no disponible: Verify $method $path"
  case "$REMOVE_HTTP_STATUS" in 200|201|204|404) ;; *) fail "Verify devolvió HTTP $REMOVE_HTTP_STATUS para $method $path; respuesta privada, retirada interrumpida.";; esac
}
remove_verify_login() {
  [[ "$VERIFY_TENANT" =~ ^https://[a-zA-Z0-9-]+\.verify\.ibm\.com$ ]] || fail 'VERIFY_TENANT no válido'
  [ -n "${VERIFY_ADMIN_CLIENT_ID:-}" ] && [ -n "${VERIFY_ADMIN_CLIENT_SECRET:-}" ] || fail 'Faltan las credenciales administrativas Verify en .env'
  jq -nr '"Authorization: Basic "+((env.VERIFY_ADMIN_CLIENT_ID+":"+env.VERIFY_ADMIN_CLIENT_SECRET)|@base64)' > "$REMOVE_WORK/verify.headers"
  remove_api POST /oauth2/token "$REMOVE_WORK/token.json" --header 'Content-Type: application/x-www-form-urlencoded' --data 'grant_type=client_credentials'
  [ "$REMOVE_HTTP_STATUS" = 200 ] || fail 'No se pudo autenticar en Verify'
  jq -er '"Authorization: Bearer "+.access_token' "$REMOVE_WORK/token.json" > "$REMOVE_WORK/verify.headers"
}
remove_add_target() {
  local kind=$1 name=$2 id=$3 path=$4
  [ -n "$id" ] || return 0
  [[ "$id" =~ ^[a-zA-Z0-9-]+$ ]] || fail 'ID inesperado en el inventario de Verify'
  jq --arg kind "$kind" --arg name "$name" --arg id "$id" --arg path "$path/$id" \
    '.+[{kind:$kind,name:$name,id:$id,path:$path}]' "$REMOVE_WORK/targets.json" > "$REMOVE_WORK/targets.next"
  mv "$REMOVE_WORK/targets.next" "$REMOVE_WORK/targets.json"
}
remove_verify_inventory() {
  local name id role gid
  printf '[]' > "$REMOVE_WORK/targets.json"
  remove_api GET /v1.0/sts/oauth/clients "$REMOVE_WORK/sts.json"
  jq -e '(.clients|type=="array") and (.total == (.clients|length))' "$REMOVE_WORK/sts.json" >/dev/null || fail 'Inventario STS incompleto; no se elimina una lista paginada parcialmente'
  id=$(jq -r '[.clients[]|select(.clientName=="vault-chatbot-sts")|.clientId]|if length>1 then error("Duplicate STS") else .[0]//empty end' "$REMOVE_WORK/sts.json")
  remove_add_target sts vault-chatbot-sts "$id" /v1.0/sts/oauth/clients
  remove_api GET /v1.0/applications "$REMOVE_WORK/apps.json"
  jq -e '(._embedded.applications|type=="array") and (.totalCount == (._embedded.applications|length))' "$REMOVE_WORK/apps.json" >/dev/null || fail 'Inventario de aplicaciones incompleto; no se elimina una lista paginada parcialmente'
  for name in vault-chatbot-oidc vault-chatbot-research vault-chatbot-xai vault-chatbot-openai vault-chatbot-anthropic; do
    id=$(jq -r --arg name "$name" '[._embedded.applications[]|select(.name==$name)|._links.self.href|split("/")[-1]]|if length>1 then error("Duplicate app") else .[0]//empty end' "$REMOVE_WORK/apps.json")
    remove_add_target app "$name" "$id" /v1.0/applications
  done
  for role in reader writer supervisor; do
    name="lumen-$role"
    remove_api GET /v2.0/Users "$REMOVE_WORK/user-list.json" --get --data-urlencode "filter=userName eq \"$name\""
    jq -e --arg name "$name" '.totalResults==(.Resources|length) and (.totalResults<=1) and all(.Resources[];.userName==$name)' "$REMOVE_WORK/user-list.json" >/dev/null || fail 'Usuario ambiguo o inventario incompleto'
    id=$(jq -r '.Resources[0].id//empty' "$REMOVE_WORK/user-list.json")
    remove_add_target user "$name" "$id" /v2.0/Users
    name="chatbot-${role}s"
    remove_api GET /v2.0/Groups "$REMOVE_WORK/group-list.json" --get --data-urlencode "filter=displayName eq \"$name\""
    jq -e --arg name "$name" '.totalResults==(.Resources|length) and (.totalResults<=1) and all(.Resources[];.displayName==$name)' "$REMOVE_WORK/group-list.json" >/dev/null || fail 'Grupo ambiguo o inventario incompleto'
    gid=$(jq -r '.Resources[0].id//empty' "$REMOVE_WORK/group-list.json")
    remove_add_target group "$name" "$gid" /v2.0/Groups
  done
  # Deleting apps removes their assignments; groups go before their test users.
  jq 'sort_by(if .kind=="sts" then 0 elif .kind=="app" then 1 elif .kind=="group" then 2 else 3 end)' "$REMOVE_WORK/targets.json" > "$REMOVE_WORK/targets.next"
  mv "$REMOVE_WORK/targets.next" "$REMOVE_WORK/targets.json"
  while IFS=$'\t' read -r kind name id path; do
    remove_validate_target "$kind" "$name" "$id" "$path"
  done < <(jq -r '.[]|[.kind,.name,.id,.path]|@tsv' "$REMOVE_WORK/targets.json")
}
remove_validate_target() {
  local kind=$1 name=$2 id=$3 path=$4
  # Re-read by immutable ID immediately before DELETE; names alone are not enough.
  remove_api GET "$path" "$REMOVE_WORK/detail.json"
  [ "$REMOVE_HTTP_STATUS" != 404 ] || return 0
  case "$kind" in
    app)
      jq -e --arg name "$name" --arg admin "$VERIFY_ADMIN_CLIENT_ID" \
        '.name==$name and .providers.oidc.properties.clientId!=null and .providers.oidc.properties.clientId!=$admin' "$REMOVE_WORK/detail.json" >/dev/null || fail "La aplicación $name no coincide o es el cliente administrativo";;
    sts)
      jq -e --arg name "$name" --arg admin "$VERIFY_ADMIN_CLIENT_ID" '.clientName==$name and .clientId!=$admin' "$REMOVE_WORK/detail.json" >/dev/null || fail 'STS inesperado';;
    user)
      jq -e --arg name "$name" --arg id "$id" '.id==$id and .userName==$name and .["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"].realm=="cloudIdentityRealm" and any(.emails[]?;.value==($name+"@example.invalid"))' "$REMOVE_WORK/detail.json" >/dev/null || fail "El usuario $name no es la cuenta ficticia esperada";;
    group)
      jq -e --arg name "$name" --arg id "$id" --slurpfile targets "$REMOVE_WORK/targets.json" \
        '.id==$id and .displayName==$name and all(.members[]?; .value as $uid | any($targets[0][];.kind=="user" and .id==$uid))' "$REMOVE_WORK/detail.json" >/dev/null || fail "El grupo $name contiene miembros ajenos a la demo";;
    *) fail 'Tipo Verify no permitido';;
  esac
}
remove_verify_apply() {
  local kind name id path delete_path attempt
  cp "$REMOVE_WORK/targets.json" "$REMOVE_WORK/to-delete.json"
  while IFS=$'\t' read -r kind name id path; do
    remove_validate_target "$kind" "$name" "$id" "$path"
    [ "$REMOVE_HTTP_STATUS" != 404 ] || continue
    delete_path=$path
    case "$kind" in user|group) delete_path="$path?notifyType=NONE";; esac
    remove_api DELETE "$delete_path" "$REMOVE_WORK/deleted.json"
    for attempt in 1 2 3 4 5; do
      remove_api GET "$path" "$REMOVE_WORK/detail.json"
      [ "$REMOVE_HTTP_STATUS" != 404 ] || break
      sleep 1
    done
    [ "$REMOVE_HTTP_STATUS" = 404 ] || fail "Verify sigue devolviendo $name después de DELETE"
    printf 'Eliminado en Verify: %s (%s)\n' "$name" "$id"
  done < <(jq -r '.[]|[.kind,.name,.id,.path]|@tsv' "$REMOVE_WORK/to-delete.json")
  remove_verify_inventory
  jq -e 'length==0' "$REMOVE_WORK/targets.json" >/dev/null || fail 'Quedan recursos Lumen en Verify'
}
