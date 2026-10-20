# 02 · MySQL Enterprise, KMIP y roles dinámicos

[Índice](README.md) · Requiere [01](01-vault.md) · Siguiente: [Verify](03-verify.md)

## 1. Configurar KMIP en el namespace root


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
export VAULT_NAMESPACE=''
vault secrets list
```

Si `kmip/` no existe, habilitarlo. Los siguientes comandos crean su configuración, scope y rol para MySQL:

```bash
vault secrets enable kmip
vault write kmip/config listen_addrs=0.0.0.0:5696 \
  server_hostnames=vault-kmip.vault.svc.cluster.local default_tls_client_ttl=365d
vault write -f kmip/scope/my-service
vault write kmip/scope/my-service/role/admin operation_all=true tls_client_ttl=365d
vault read -format=json kmip/ca | jq -er .data.ca_pem > "$MANUAL/CA.pem"
vault write -format=json kmip/scope/my-service/role/admin/credential/generate \
  format=pem > "$MANUAL/kmip-credential.json"
jq -er .data.certificate "$MANUAL/kmip-credential.json" > "$MANUAL/cert.pem"
jq -er .data.private_key "$MANUAL/kmip-credential.json" > "$MANUAL/key.pem"
printf 'SERVER=vault-kmip.vault.svc.cluster.local:5696\nSTANDBY_SERVER=vault-kmip.vault.svc.cluster.local:5696\n' \
  > "$MANUAL/okvclient.ora"
vault read kmip/config
vault read kmip/scope/my-service/role/admin
```

MySQL guarda sus claves de cifrado en el servidor KMIP de Vault y se autentica con este certificado cliente. El rol `admin` permite todas las operaciones KMIP dentro de `my-service`, reproduciendo el laboratorio. No es una credencial SQL.

## 2. Preparar Kubernetes y desplegar MySQL

```bash
"${K[@]}" create namespace mysql --dry-run=client -o yaml | "${K[@]}" apply -f -
jq -n '{auths:{"container-registry.oracle.com":{
  username:env.ORACLE_REG_EMAIL,password:env.ORACLE_REG_PASSWORD,
  auth:((env.ORACLE_REG_EMAIL+":"+env.ORACLE_REG_PASSWORD)|@base64)}}}' \
  > "$MANUAL/dockerconfig.json"
"${K[@]}" -n mysql create secret generic oracle-registry \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=".dockerconfigjson=$MANUAL/dockerconfig.json"
printf '%s' "$MYSQL_ROOT_PASSWORD" > "$MANUAL/mysql-root-password"
"${K[@]}" -n mysql create secret generic mysql-root \
  --from-file="password=$MANUAL/mysql-root-password"
"${K[@]}" -n mysql create configmap mysql-tde-config --from-file=my.cnf=deploy/my.cnf
"${K[@]}" -n mysql create secret generic mysql-keyring-okv \
  --from-file="okvclient.ora=$MANUAL/okvclient.ora" --from-file="CA.pem=$MANUAL/CA.pem" \
  --from-file="cert.pem=$MANUAL/cert.pem" --from-file="key.pem=$MANUAL/key.pem"
rm -- "$MANUAL/dockerconfig.json" "$MANUAL/mysql-root-password" "$MANUAL/kmip-credential.json"
arch=$("${K[@]}" get nodes -o json | jq -er '.items[0].status.nodeInfo.architecture')
tag=8.3.0
[ "$arch" != arm64 ] || tag=8.3.0-aarch64
sed "s/__MYSQL_TAG__/$tag/g" deploy/mysql.yaml > "$MANUAL/mysql.yaml"
"${K[@]}" apply -f "$MANUAL/mysql.yaml"
"${K[@]}" -n mysql rollout status statefulset/mysql-enterprise --timeout=600s
```

[my.cnf](../../deploy/my.cnf) carga `keyring_okv.so` al iniciar MySQL. [mysql.yaml](../../deploy/mysql.yaml) contiene el Service KMIP que apunta al Vault activo, un initContainer que prepara los certificados, el StatefulSet y un PVC de 10 GiB.

## 3. Crear la base y los datos de ejemplo

Esta función ejecuta el cliente MySQL dentro del pod; la contraseña root procede de su Kubernetes Secret.

```bash
mysql_admin() {
  "${K[@]}" -n mysql exec -i mysql-enterprise-0 -c mysql -- \
    sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4'
}
mysql_admin <<'SQL'
SELECT PLUGIN_NAME, PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS
 WHERE PLUGIN_NAME='keyring_okv';
SQL
```

Debe indicar `ACTIVE`. Crear las tablas con `ENCRYPTION='Y'`:

```bash
mysql_admin <<'SQL'
CREATE DATABASE IF NOT EXISTS scripting;
CREATE TABLE IF NOT EXISTS scripting.test_encryption (
  ID INT PRIMARY KEY, server_name VARCHAR(120) NOT NULL
) ENGINE=InnoDB ENCRYPTION='Y';
INSERT INTO scripting.test_encryption (ID,server_name)
SELECT demo.ID,demo.server_name FROM (
 SELECT 1 AS ID,'solar-gateway-demo' AS server_name
 UNION ALL SELECT 2,'energy-meter-demo'
 UNION ALL SELECT 3,'storage-controller-demo'
) AS demo
WHERE NOT EXISTS (SELECT 1 FROM scripting.test_encryption);
CREATE TABLE IF NOT EXISTS scripting.energy_plans (
  id INT PRIMARY KEY, name VARCHAR(80) NOT NULL,
  description VARCHAR(255) NOT NULL,
  price_kwh DECIMAL(8,4) NOT NULL, renewable BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB ENCRYPTION='Y';
INSERT INTO scripting.energy_plans VALUES
 (1,'Luz Equilibrio','Precio estable durante todo el día. Datos ficticios de demostración.',0.1450,TRUE),
 (2,'Luz Noche','Plan de ejemplo orientado al consumo nocturno.',0.1190,TRUE),
 (3,'Solar Contigo','Plan ficticio para hogares con autoconsumo.',0.1320,TRUE)
ON DUPLICATE KEY UPDATE name=VALUES(name),description=VALUES(description),price_kwh=VALUES(price_kwh),renewable=VALUES(renewable);
CREATE TABLE IF NOT EXISTS scripting.service_requests (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 subject_id VARCHAR(120) NOT NULL,
 plan_id INT NOT NULL, note VARCHAR(500) NOT NULL,
 status VARCHAR(30) NOT NULL DEFAULT 'borrador',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB ENCRYPTION='Y';
SQL
```

Las tarifas son ficticias. La cuarta tabla, `energy_applications`, se crea en el capítulo 05 para almacenar ciphertext y tokens.

## 4. Conectar el motor Database con MySQL

La cuenta `vault_chatbot_admin` crea y elimina usuarios SQL temporales. Vault rota su contraseña al terminar; Lumen no conoce esa cuenta.

```bash
export VAULT_NAMESPACE=verify
vault secrets enable database
openssl rand -hex 24 > "$MANUAL/mysql-admin-password"
DB_PASSWORD=$(cat "$MANUAL/mysql-admin-password")
mysql_admin <<SQL
CREATE USER 'vault_chatbot_admin'@'%' IDENTIFIED BY '$DB_PASSWORD';
GRANT CREATE USER ON *.* TO 'vault_chatbot_admin'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON scripting.* TO 'vault_chatbot_admin'@'%' WITH GRANT OPTION;
SQL
unset DB_PASSWORD
jq -n --rawfile password "$MANUAL/mysql-admin-password" '{
  plugin_name:"mysql-database-plugin",
  connection_url:"{{username}}:{{password}}@tcp(mysql-enterprise.mysql.svc.cluster.local:3306)/",
  allowed_roles:["chatbot-readonly","chatbot-readwrite"],username:"vault_chatbot_admin",
  password:($password|rtrimstr("\n")),
  root_rotation_statements:["ALTER USER '\''{{username}}'\''@'\''%'\'' IDENTIFIED BY '\''{{password}}'\'';"]
}' | vault write database/config/chatbot-mysql -
vault write -f database/rotate-root/chatbot-mysql
rm -- "$MANUAL/mysql-admin-password"
```

Si `database/config/chatbot-mysql` ya existe, leerlo y omitir esta creación/rotación inicial. No restablecer el usuario MySQL con una contraseña inventada: perderías la coherencia con Vault.

## 5. Definir roles read-only y read-write

```bash
for role in readonly readwrite; do
  grants=SELECT
  [ "$role" = readonly ] || grants='SELECT, INSERT, UPDATE, DELETE'
  cat > "$MANUAL/create-$role.sql" <<SQL
CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}';
GRANT $grants ON scripting.* TO '{{name}}'@'%';
SQL
  jq -n --rawfile sql "$MANUAL/create-$role.sql" '{
    db_name:"chatbot-mysql",creation_statements:[$sql],
    revocation_statements:["DROP USER IF EXISTS '\''{{name}}'\''@'\''%'\'';"],
    default_ttl:"120s",max_ttl:"300s"
  }' | vault write "database/roles/chatbot-$role" -
done
vault read database/roles/chatbot-readonly
vault read database/roles/chatbot-readwrite
```

## 6. Emitir y revocar una credencial de prueba

Esta prueba usa el administrador de Vault, por lo que verifica el motor, no los permisos OBO:

```bash
vault read -format=json database/creds/chatbot-readonly > "$MANUAL/db-test.json"
jq '{lease_id,lease_duration,renewable,username:.data.username}' "$MANUAL/db-test.json"
vault lease revoke "$(jq -er .lease_id "$MANUAL/db-test.json")"
mysql_admin <<'SQL'
SELECT NAME,ENCRYPTION FROM INFORMATION_SCHEMA.INNODB_TABLESPACES
 WHERE NAME LIKE 'scripting/%';
SQL
```

Resultado: lease de 120 segundos y tablas con cifrado `Y`. La prueba de acceso SQL con el usuario humano se explica en [OBO manual](11-obo.md). Para la app, mantener en otra terminal:

```bash
kubectl --context workshop -n mysql port-forward --address 127.0.0.1 svc/mysql-enterprise 13306:3306
```

Fuentes locales: [mysql.sh](../../scripts/demo/mysql.sh), [01-database.sh](../../chatbot/scripts/01-database.sh).
