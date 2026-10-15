path "spiffe/role/lumen-openai/mintjwt" {
  capabilities = ["update"]
  required_parameters = ["audience"]
  allowed_parameters = { "audience" = ["https://api.openai.com/v1"] }
}
