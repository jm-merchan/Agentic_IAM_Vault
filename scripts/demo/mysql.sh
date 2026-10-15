#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
MSTATE="$LUMEN_STATE_DIR/mysql"
mkdir -p "$MSTATE"
chmod 700 "$MSTATE"
if ! vault secrets list -format=json | jq -e '."kmip/".type=="kmip"' >/dev/null; then vault secrets enable kmip >/dev/null; fi
# A newly enabled mount has no configuration yet (HTTP 404). Do not treat
# authentication or server errors as an empty configuration.
kmip_status=$(printf 'X-Vault-Token: %s\n' "$VAULT_TOKEN" | curl --silent --show-error \
  --connect-timeout 10 --max-time 30 --cacert "$VAULT_CACERT" --header @- \
  --output "$MSTATE/kmip-config.json" --write-out '%{http_code}' "$VAULT_ADDR/v1/kmip/config")
case "$kmip_status" in
  200) jq -e '.data|type=="object"' "$MSTATE/kmip-config.json" >/dev/null || fail 'Respuesta KMIP inválida';;
  404) printf '{"data":{}}\n' > "$MSTATE/kmip-config.json";;
  *) fail "No se pudo leer kmip/config (HTTP $kmip_status); no se modifica la configuración";;
esac
if ! jq -e '(.data.listen_addrs // [])|index("0.0.0.0:5696")' "$MSTATE/kmip-config.json" >/dev/null; then
  vault write kmip/config listen_addrs=0.0.0.0:5696 server_hostnames=vault-kmip.vault.svc.cluster.local default_tls_client_ttl=365d >/dev/null
fi
if ! "${K[@]}" -n mysql get statefulset mysql-enterprise >/dev/null 2>&1; then
  vault write -f kmip/scope/my-service >/dev/null
  vault write kmip/scope/my-service/role/admin operation_all=true tls_client_ttl=365d >/dev/null
  vault read -format=json kmip/ca | jq -er .data.ca_pem > "$MSTATE/CA.pem"
  vault write -format=json kmip/scope/my-service/role/admin/credential/generate format=pem > "$MSTATE/credential.json"
  jq -er .data.certificate "$MSTATE/credential.json" > "$MSTATE/cert.pem"
  jq -er .data.private_key "$MSTATE/credential.json" > "$MSTATE/key.pem"
  rm "$MSTATE/credential.json"
  printf 'SERVER=vault-kmip.vault.svc.cluster.local:5696\nSTANDBY_SERVER=vault-kmip.vault.svc.cluster.local:5696\n' > "$MSTATE/okvclient.ora"
  "${K[@]}" create namespace mysql --dry-run=client -o yaml | "${K[@]}" apply -f -
  jq -n '{auths:{"container-registry.oracle.com":{username:env.ORACLE_REG_EMAIL,password:env.ORACLE_REG_PASSWORD,auth:((env.ORACLE_REG_EMAIL+":"+env.ORACLE_REG_PASSWORD)|@base64)}}}' > "$MSTATE/dockerconfig.json"
  "${K[@]}" -n mysql create secret generic oracle-registry --type=kubernetes.io/dockerconfigjson --from-file=".dockerconfigjson=$MSTATE/dockerconfig.json" --dry-run=client -o json | "${K[@]}" apply -f -
  rm "$MSTATE/dockerconfig.json"
  printf '%s' "$MYSQL_ROOT_PASSWORD" > "$MSTATE/root-password"
  "${K[@]}" -n mysql create secret generic mysql-root --from-file="password=$MSTATE/root-password" --dry-run=client -o json | "${K[@]}" apply -f -
  rm "$MSTATE/root-password"
  "${K[@]}" -n mysql create configmap mysql-tde-config --from-file="my.cnf=$DEMO_ROOT/deploy/my.cnf" --dry-run=client -o yaml | "${K[@]}" apply -f -
  "${K[@]}" -n mysql create secret generic mysql-keyring-okv --from-file="okvclient.ora=$MSTATE/okvclient.ora" --from-file="CA.pem=$MSTATE/CA.pem" --from-file="cert.pem=$MSTATE/cert.pem" --from-file="key.pem=$MSTATE/key.pem" --dry-run=client -o json | "${K[@]}" apply -f -
  arch=$("${K[@]}" get nodes -o json | jq -er '.items[0].status.nodeInfo.architecture')
  tag=8.3.0
  [ "$arch" != arm64 ] || tag=8.3.0-aarch64
  sed "s/__MYSQL_TAG__/$tag/g" "$DEMO_ROOT/deploy/mysql.yaml" > "$MSTATE/mysql.yaml"
  "${K[@]}" apply -f "$MSTATE/mysql.yaml"
fi
"${K[@]}" -n mysql rollout status statefulset/mysql-enterprise --timeout=600s
actual=$("${K[@]}" -n mysql exec mysql-enterprise-0 -c mysql -- printenv MYSQL_ROOT_PASSWORD)
[ "$actual" = "$MYSQL_ROOT_PASSWORD" ] || fail 'MYSQL_ROOT_PASSWORD de .env difiere del MySQL existente; no se rota automáticamente.'
unset actual
"${K[@]}" -n mysql exec mysql-enterprise-0 -c mysql -- sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -Nse "SELECT COUNT(*) FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME=\"keyring_okv\" AND PLUGIN_STATUS=\"ACTIVE\""' | grep -qx 1
start_forward mysql mysql svc/mysql-enterprise 13306 3306
echo 'MySQL disponible con keyring_okv activo. Datos y certificados existentes conservados.'
