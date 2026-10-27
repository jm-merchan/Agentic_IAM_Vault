# 02 · MySQL Enterprise, KMIP and dynamic roles

[Index](README.md) · Requires [01](01-vault.md) · Next: [Verify](03-verify.md)

## 1. Configure KMIP in the root namespace


```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
```

```bash
export VAULT_NAMESPACE=''
vault secrets list
```

If `kmip/` does not exist, enable it. The following commands create its configuration, scope and role for MySQL:

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

MySQL stores its encryption keys in Vault's KMIP server and authenticates with this client certificate. The `admin` role allows all KMIP operations inside `my-service`, reproducing the lab. It is not an SQL credential.

## 2. Prepare Kubernetes and deploy MySQL

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

[my.cnf](../../deploy/my.cnf) loads `keyring_okv.so` when MySQL starts. [mysql.yaml](../../deploy/mysql.yaml) contains the KMIP Service pointing to the active Vault, an initContainer that prepares the certificates, the StatefulSet and a 10 GiB PVC.

## 3. Create the database and the sample data

This function runs the MySQL client inside the pod; the root password comes from its Kubernetes Secret.

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

It must show `ACTIVE`. Create the tables with `ENCRYPTION='Y'`:

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

The tariffs are fictitious. The fourth table, `energy_applications`, is created in chapter 05 to store ciphertext and tokens.

## 4. Connect the Database engine to MySQL

The `vault_chatbot_admin` account creates and deletes temporary SQL users. Vault rotates its password at the end; Lumen does not know this account.

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

If `database/config/chatbot-mysql` already exists, read it and skip this initial creation/rotation. Do not reset the MySQL user with a made-up password: you would lose consistency with Vault.

## 5. Define read-only and read-write roles

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

## 6. Issue and revoke a test credential

This test uses the Vault administrator, so it verifies the engine, not the OBO permissions:

```bash
vault read -format=json database/creds/chatbot-readonly > "$MANUAL/db-test.json"
jq '{lease_id,lease_duration,renewable,username:.data.username}' "$MANUAL/db-test.json"
vault lease revoke "$(jq -er .lease_id "$MANUAL/db-test.json")"
mysql_admin <<'SQL'
SELECT NAME,ENCRYPTION FROM INFORMATION_SCHEMA.INNODB_TABLESPACES
 WHERE NAME LIKE 'scripting/%';
SQL
```

Result: a 120-second lease and tables with encryption `Y`. The SQL access test with the human user is explained in [manual OBO](11-obo.md). For the app, keep this running in another terminal:

```bash
kubectl --context workshop -n mysql port-forward --address 127.0.0.1 svc/mysql-enterprise 13306:3306
```

Local sources: [mysql.sh](../../scripts/demo/mysql.sh), [01-database.sh](../../chatbot/scripts/01-database.sh).
