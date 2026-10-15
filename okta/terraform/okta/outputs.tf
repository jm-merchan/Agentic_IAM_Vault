output "client_id" {
  description = "EXTERNAL_ID for the subsequent Vault configuration."
  value       = okta_app_oauth.agentic.client_id
}

output "auth_server_id" {
  description = "Existing custom authorization server managed by Okta."
  value       = data.okta_auth_server.default.id
}

output "issuer" {
  description = "Token issuer used by this demo."
  value       = data.okta_auth_server.default.issuer
}

output "jwks_uri" {
  description = "Public signing keys for validating Okta tokens."
  value       = "${data.okta_auth_server.default.issuer}/v1/keys"
}

output "human_client_id" {
  description = "Client for the interactive human authorization flow."
  value       = okta_app_oauth.human.client_id
}
