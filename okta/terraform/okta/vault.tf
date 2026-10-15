# The existing secrets/ KV v2 mount is shared with the bootstrap credentials.
# Demo policies permit only the two explicit demo paths below.
resource "vault_policy" "agent_read" {
  name   = "okta-agentic-read"
  policy = <<-EOT
    path "secrets/data/agentic-demo/shared" {
      capabilities = ["read"]
    }
  EOT
}

resource "vault_policy" "human_read" {
  name   = "okta-agentic-human"
  policy = <<-EOT
    path "secrets/data/agentic-demo/shared" {
      capabilities = ["read"]
    }
    path "secrets/data/agentic-demo/human-only" {
      capabilities = ["read"]
    }
  EOT
}

resource "vault_oauth_resource_server_config_profile" "okta" {
  profile_name                   = "okta-agentic"
  issuer_id                      = data.okta_auth_server.default.issuer
  use_jwks                       = true
  jwks_uri                       = "${data.okta_auth_server.default.issuer}/v1/keys"
  audiences                      = ["api://default"]
  user_claim                     = "sub"
  supported_algorithms           = ["RS256"]
  jwt_type                       = "access_token"
  no_default_policy              = true
  optional_authorization_details = false
}

resource "vault_identity_entity" "agent" {
  name     = "okta-agentic-agent"
  policies = [vault_policy.agent_read.name]
  metadata = { managed_by = "terraform", purpose = "okta-agentic-demo" }
}

resource "vault_identity_entity_alias" "agent" {
  name           = "okta-agentic-actor"
  canonical_id   = vault_identity_entity.agent.id
  mount_accessor = "oauth-resource-server_root_${vault_oauth_resource_server_config_profile.okta.id}"
  issuer         = data.okta_auth_server.default.issuer
  external_id    = okta_app_oauth.agentic.client_id
}

resource "vault_agent_registration" "agent" {
  display_name                   = "okta-agentic-agent"
  entity_id                      = vault_identity_entity.agent.id
  description                    = "Okta agent: autonomous access and delegation on behalf of a human."
  ceiling_policies               = [vault_policy.agent_read.name]
  no_default_ceiling_policy      = true
  optional_authorization_details = true
}

variable "human_subject" {
  description = "Verified sub claim from the human access token; null until the interactive sign-in completes."
  type        = string
  default     = null
  nullable    = true
}

resource "vault_identity_entity" "human" {
  name     = "okta-agentic-human"
  policies = [vault_policy.human_read.name]
  metadata = { managed_by = "terraform", purpose = "okta-agentic-demo" }
}

resource "vault_identity_entity_alias" "human" {
  count          = var.human_subject == null ? 0 : 1
  name           = "okta-agentic-subject"
  canonical_id   = vault_identity_entity.human.id
  mount_accessor = "oauth-resource-server_root_${vault_oauth_resource_server_config_profile.okta.id}"
  issuer         = data.okta_auth_server.default.issuer
  external_id    = var.human_subject
}

resource "vault_kv_secret_v2" "demo" {
  for_each  = toset(["shared", "human-only"])
  mount     = "secrets"
  name      = "agentic-demo/${each.key}"
  data_json = jsonencode({ message = "Synthetic demonstration data: ${each.key}" })
}

output "agent_entity_id" {
  description = "Vault identity and agent registry identifier."
  value       = vault_identity_entity.agent.id
}
