#!/usr/bin/env bash
# Bootstrap only. The chatbot never receives this administrative Vault token.
source "$(dirname "$0")/../../verify/scripts/common.sh"
mysql_admin() {
  kubectl --context workshop -n mysql exec -i mysql-enterprise-0 -c mysql -- \
    sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4'
}
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
if ! vault secrets list -format=json | jq -e 'has("database/")' >/dev/null; then
  vault secrets enable database >/dev/null
fi
if ! vault read database/config/chatbot-mysql >/dev/null 2>&1; then
  openssl rand -hex 24 > "$TMP_WORK/mysql-password"
  CHATBOT_DB_PASSWORD=$(cat "$TMP_WORK/mysql-password")
  mysql_admin <<SQL
CREATE USER IF NOT EXISTS 'vault_chatbot_admin'@'%' IDENTIFIED BY '$CHATBOT_DB_PASSWORD';
ALTER USER 'vault_chatbot_admin'@'%' IDENTIFIED BY '$CHATBOT_DB_PASSWORD';
GRANT CREATE USER ON *.* TO 'vault_chatbot_admin'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON scripting.* TO 'vault_chatbot_admin'@'%' WITH GRANT OPTION;
SQL
  jq -n --rawfile password "$TMP_WORK/mysql-password" '{plugin_name:"mysql-database-plugin",connection_url:"{{username}}:{{password}}@tcp(mysql-enterprise.mysql.svc.cluster.local:3306)/",allowed_roles:["chatbot-readonly","chatbot-readwrite"],username:"vault_chatbot_admin",password:($password|rtrimstr("\n")),root_rotation_statements:["ALTER USER '\''{{username}}'\''@'\''%'\'' IDENTIFIED BY '\''{{password}}'\'';"]}' | vault write database/config/chatbot-mysql - >/dev/null
  vault write -f database/rotate-root/chatbot-mysql >/dev/null
  unset CHATBOT_DB_PASSWORD
fi
for role in readonly readwrite; do
  grants=SELECT
  [ "$role" = readonly ] || grants='SELECT, INSERT, UPDATE, DELETE'
  cat > "$TMP_WORK/create.sql" <<SQL
CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}';
GRANT $grants ON scripting.* TO '{{name}}'@'%';
SQL
  jq -n --rawfile sql "$TMP_WORK/create.sql" '{db_name:"chatbot-mysql",creation_statements:[$sql],revocation_statements:["DROP USER IF EXISTS '\''{{name}}'\''@'\''%'\'';"],default_ttl:"120s",max_ttl:"300s"}' | vault write "database/roles/chatbot-$role" - >/dev/null
done
printf 'Database roles ready in namespace verify: chatbot-readonly and chatbot-readwrite. TTL 120s.\n'
if vault kv get -mount=secrets chatbot/contracts >/dev/null 2>&1; then
  bash "$(dirname "$0")/configure-contracts.sh"
fi
