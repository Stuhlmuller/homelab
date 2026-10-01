terraform {
  required_version = ">= 1.9.0"
  required_providers {
    openrouter = {
      source  = "registry.terraform.io/OpenRouterTeam/openrouter"
      version = "0.3.19"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

resource "openrouter_api_key" "this" {
  name     = var.key_name
  disabled = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ssm_parameter" "this" {
  name        = var.parameter_name
  description = "OpenRouter-issued inference key; managed by OpenTofu."
  type        = "SecureString"
  key_id      = var.kms_key_id
  value       = openrouter_api_key.this.key
  tags        = var.tags

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = try(startswith(openrouter_api_key.this.key, "sk-or-"), false)
      error_message = "The provider must retain the issued key. Restore encrypted state rather than importing an unrecoverable key hash."
    }
  }
}
