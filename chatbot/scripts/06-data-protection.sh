#!/usr/bin/env bash
# Application-layer protection, additional to the existing MySQL KMIP encryption.
source "$(dirname "$0")/../../verify/scripts/common.sh"
for engine in transit transform; do
  if ! vault secrets list -format=json | jq -e --arg path "$engine/" 'has($path)' >/dev/null; then
    vault secrets enable "$engine" >/dev/null
  fi
  vault secrets list -format=json | jq -e --arg path "$engine/" --arg engine "$engine" '.[$path].type==$engine' >/dev/null
done
if ! vault read transit/keys/lumen-applications >/dev/null 2>&1; then
  vault write transit/keys/lumen-applications type=aes256-gcm96 exportable=false allow_plaintext_backup=false >/dev/null
fi
for field in dni iban; do
  name="lumen-$field"
  if ! vault read "transform/transformations/tokenization/$name" >/dev/null 2>&1; then
    vault write "transform/transformations/tokenization/$name" allowed_roles="$name" convergence=false mapping_mode=default >/dev/null
  fi
  vault write "transform/role/$name" transformations="$name" >/dev/null
done
kubectl --context workshop -n mysql exec -i mysql-enterprise-0 -c mysql -- \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --default-character-set=utf8mb4' <<'SQL'
CREATE TABLE IF NOT EXISTS scripting.energy_applications (
  application_id CHAR(36) PRIMARY KEY,
  subject_id VARCHAR(120) NOT NULL,
  plan_id INT NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'recibida',
  profile_ciphertext TEXT NOT NULL,
  dni_token TEXT NOT NULL,
  iban_token TEXT NOT NULL,
  dni_hint VARCHAR(40) NOT NULL,
  iban_hint VARCHAR(80) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (plan_id) REFERENCES scripting.energy_plans(id)
) ENGINE=InnoDB ENCRYPTION='Y';
SQL
printf 'verify: Transit + Transform preparados; MySQL energy_applications guarda ciphertext y tokens.\n'
