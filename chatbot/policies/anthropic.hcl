path "spiffe/role/lumen-anthropic/mintjwt" {
  capabilities = ["update"]
  required_parameters = ["audience"]
  allowed_parameters = {
    "audience" = ["https://api.anthropic.com"]
  }
}
path "secrets/data/verify-admin" { capabilities = ["deny"] }
