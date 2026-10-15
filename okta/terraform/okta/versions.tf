terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.12.0"
    }
    okta = {
      source  = "okta/okta"
      version = "~> 7.0.0"
    }
  }

  backend "local" {}
}
