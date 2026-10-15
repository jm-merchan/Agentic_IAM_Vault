data "okta_auth_server" "default" {
  name = "default"
}

resource "okta_app_oauth" "human" {
  label                      = "Vault Agentic IAM Human"
  skip_authentication_policy = true
  type                       = "web"
  token_endpoint_auth_method = "client_secret_basic"
  omit_secret                = true
  implicit_assignment        = true
  pkce_required              = true
  redirect_uris              = ["http://localhost:9876/callback"]
  response_types             = ["code"]
  grant_types = [
    "authorization_code",
    "refresh_token",
  ]
  refresh_token_rotation = "ROTATE"
  refresh_token_leeway   = 30
}

resource "okta_auth_server_scope" "vault_read" {
  auth_server_id   = data.okta_auth_server.default.id
  name             = "vault.read"
  display_name     = "Vault Read"
  description      = "Read access requested by the Vault Agentic IAM demo. Vault enforces its own policies."
  consent          = "IMPLICIT"
  default          = true
  metadata_publish = "ALL_CLIENTS"
}

resource "okta_auth_server_policy" "agentic" {
  auth_server_id   = data.okta_auth_server.default.id
  name             = "Vault Agentic IAM"
  description      = "Token issuance for the Vault Agentic IAM application."
  priority         = 1
  client_whitelist = [okta_app_oauth.human.client_id, okta_app_oauth.agentic.client_id]
}

resource "okta_auth_server_policy_rule" "agentic" {
  auth_server_id  = data.okta_auth_server.default.id
  policy_id       = okta_auth_server_policy.agentic.id
  name            = "AI default access"
  priority        = 1
  group_whitelist = ["EVERYONE"]
  grant_type_whitelist = [
    "authorization_code",
    "client_credentials",
    "urn:ietf:params:oauth:grant-type:device_code",
    "urn:ietf:params:oauth:grant-type:token-exchange",
  ]
  scope_whitelist = ["openid", "profile", "email", "offline_access", okta_auth_server_scope.vault_read.name]

  access_token_lifetime_minutes  = 60
  refresh_token_window_minutes   = 10080
  refresh_token_lifetime_minutes = 43200
}

resource "okta_app_oauth" "agentic" {
  label                      = "Vault Agentic IAM Agent"
  type                       = "service"
  token_endpoint_auth_method = "client_secret_basic"
  omit_secret                = true
  response_types             = ["token"]
  grant_types = [
    "client_credentials",
    "urn:ietf:params:oauth:grant-type:token-exchange",
  ]
}
