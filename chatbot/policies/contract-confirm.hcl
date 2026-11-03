# Human Validator policy, intersected with the CIBA actor ceiling and signed RAR.
path "database/creds/chatbot-contract" { capabilities = ["read"] }
path "transit/decrypt/lumen-applications" { capabilities = ["update"] }
path "transform/decode/lumen-dni" { capabilities = ["update"] }
path "transform/decode/lumen-iban" { capabilities = ["update"] }
path "transit/encrypt/lumen-contracts" { capabilities = ["update"] }
path "transit/decrypt/lumen-contracts" { capabilities = ["update"] }
path "secrets/data/lumen-contracts/*" { capabilities = ["create", "update", "read"] }
path "auth/token/revoke" {
  capabilities = ["update"]
  required_parameters = ["token"]
  allowed_parameters = { "token" = ["eyJ*"] }
}
