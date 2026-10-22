-- Separate schema: legacy GRANT ... ON scripting.* cannot formalize a contract.
CREATE DATABASE IF NOT EXISTS lumen_contracts;
CREATE TABLE IF NOT EXISTS lumen_contracts.contracts (
 application_id CHAR(36) PRIMARY KEY,
 contract_id CHAR(36) NOT NULL UNIQUE,
 requestor_subject VARCHAR(120) NOT NULL,
 owner_entity CHAR(36) NOT NULL,
 validator_subject VARCHAR(120) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'contratada',
 confirmed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 plan_name VARCHAR(80) NOT NULL,
 price_kwh DECIMAL(8,4) NOT NULL,
 snapshot_hash CHAR(64) NOT NULL,
 pdf_sha256 CHAR(64) NOT NULL,
 pdf_ciphertext MEDIUMTEXT NOT NULL,
 CONSTRAINT contract_status CHECK (status = 'contratada'),
 FOREIGN KEY(application_id) REFERENCES scripting.energy_applications(application_id)
) ENGINE=InnoDB ENCRYPTION='Y';
CREATE USER IF NOT EXISTS 'lumen_contract_definer'@'localhost' ACCOUNT LOCK;
GRANT SELECT ON scripting.energy_applications TO 'lumen_contract_definer'@'localhost';
GRANT SELECT ON scripting.energy_plans TO 'lumen_contract_definer'@'localhost';
-- MySQL requires UPDATE as well as SELECT for FOR UPDATE. Only the locked
-- procedure definer receives it; dynamic contract users retain EXECUTE only.
GRANT UPDATE(application_id) ON scripting.energy_applications TO 'lumen_contract_definer'@'localhost';
GRANT UPDATE(id) ON scripting.energy_plans TO 'lumen_contract_definer'@'localhost';
GRANT SELECT, INSERT ON lumen_contracts.contracts TO 'lumen_contract_definer'@'localhost';
DROP PROCEDURE IF EXISTS lumen_contracts.formalize;
DELIMITER $$
CREATE DEFINER='lumen_contract_definer'@'localhost' PROCEDURE lumen_contracts.formalize(
 IN p_application CHAR(36), IN p_contract CHAR(36), IN p_requestor VARCHAR(120),
 IN p_owner CHAR(36), IN p_validator VARCHAR(120), IN p_snapshot CHAR(64),
 IN p_pdf_hash CHAR(64), IN p_pdf MEDIUMTEXT)
SQL SECURITY DEFINER
proc: BEGIN
 DECLARE actual_hash CHAR(64) DEFAULT NULL;
 DECLARE actual_subject VARCHAR(120);
 DECLARE actual_plan VARCHAR(80);
 DECLARE actual_price DECIMAL(8,4);
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 SELECT a.subject_id,p.name,p.price_kwh,
  SHA2(CAST(JSON_ARRAY(a.application_id,a.subject_id,a.plan_id,a.profile_ciphertext,a.dni_token,a.iban_token,p.name,p.price_kwh) AS CHAR),256)
 INTO actual_subject,actual_plan,actual_price,actual_hash
 FROM scripting.energy_applications a JOIN scripting.energy_plans p ON p.id=a.plan_id
 WHERE a.application_id=p_application FOR UPDATE;
 IF actual_hash IS NULL OR actual_subject <> p_requestor THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Draft not found or owner mismatch';
 END IF;
 -- The application primary key and row lock make concurrent retries idempotent.
 IF NOT EXISTS(SELECT 1 FROM lumen_contracts.contracts WHERE application_id=p_application) THEN
  IF actual_hash <> p_snapshot OR p_requestor=p_validator OR p_validator='' OR
     p_pdf NOT LIKE 'vault:v%:%' OR LENGTH(p_pdf_hash)<>64 THEN
   SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Draft changed or invalid confirmation';
  END IF;
  INSERT INTO lumen_contracts.contracts(application_id,contract_id,requestor_subject,owner_entity,
   validator_subject,plan_name,price_kwh,snapshot_hash,pdf_sha256,pdf_ciphertext)
  VALUES(p_application,p_contract,p_requestor,p_owner,p_validator,actual_plan,actual_price,p_snapshot,p_pdf_hash,p_pdf);
 END IF;
 COMMIT;
 SELECT * FROM lumen_contracts.contracts WHERE application_id=p_application;
END$$
DELIMITER ;
GRANT EXECUTE ON PROCEDURE lumen_contracts.formalize TO 'lumen_contract_definer'@'localhost';
GRANT EXECUTE ON PROCEDURE lumen_contracts.formalize TO 'vault_chatbot_admin'@'%' WITH GRANT OPTION;
GRANT SELECT(application_id,contract_id,requestor_subject,owner_entity,validator_subject,status,confirmed_at,plan_name,price_kwh,snapshot_hash,pdf_sha256)
 ON lumen_contracts.contracts TO 'vault_chatbot_admin'@'%' WITH GRANT OPTION;
-- Once formalized, the original draft cannot be modified or deleted by legacy RW accounts.
GRANT TRIGGER ON scripting.energy_applications TO 'lumen_contract_definer'@'localhost';
DROP TRIGGER IF EXISTS scripting.lumen_contract_immutable;
DELIMITER $$
CREATE DEFINER='lumen_contract_definer'@'localhost' TRIGGER scripting.lumen_contract_immutable
 BEFORE UPDATE ON scripting.energy_applications FOR EACH ROW
BEGIN
 IF EXISTS(SELECT 1 FROM lumen_contracts.contracts WHERE application_id=OLD.application_id) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Contracted draft is immutable';
 END IF;
END$$
DELIMITER ;
