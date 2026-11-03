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
path "auth/token/renew-self" { capabilities = ["update"] }
path "auth/token/revoke-self" { capabilities = ["update"] }
