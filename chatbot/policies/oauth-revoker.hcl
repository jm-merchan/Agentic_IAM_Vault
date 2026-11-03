# Rendered by run.sh using the configured Verify issuer. Server-side lab only.
path "auth/token/revoke-oauth" {
  capabilities = ["update"]
  required_parameters = ["issuer", "unique_id", "exp"]
  allowed_parameters = {
    "issuer" = [__VERIFY_ISSUER__]
    "unique_id" = []
    "exp" = []
  }
}
# Metadata only, confined to the two dynamic roles exercised by this lab.
path "sys/leases/lookup" {
  capabilities = ["update"]
  required_parameters = ["lease_id"]
  allowed_parameters = {
    "lease_id" = ["database/creds/chatbot-readonly/*", "xai/creds/lumen/*"]
  }
}
path "auth/token/renew-self" { capabilities = ["update"] }
path "auth/token/revoke-self" { capabilities = ["update"] }
