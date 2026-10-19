terraform {
  required_version = ">= 1.10.0"

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "3.9.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
    }
  }

  encryption {
    key_provider "aws_kms" "main" {
      kms_key_id = var.kms_key_id
      key_spec   = var.kms_key_spec
      region     = var.kms_region
    }

    method "aes_gcm" "main" {
      keys = key_provider.aws_kms.main
    }

    state {
      method   = method.aes_gcm.main
      enforced = true
    }

    plan {
      method   = method.aes_gcm.main
      enforced = true
    }
  }
}

variable "user_principal_name" {
  description = "New internal cloud-only user's UPN in a verified managed tenant domain."
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+$", var.user_principal_name))
    error_message = "user_principal_name must be an explicit UPN."
  }
}

variable "display_name" {
  description = "Display name for the new unprivileged family device user."
  type        = string
}

variable "required_verified_domain" {
  description = "Optional exact UPN domain that must already be verified, managed, non-default and non-initial before this user can be created."
  type        = string
  default     = null

  validation {
    condition = (
      var.required_verified_domain == null || (
        can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.required_verified_domain)) &&
        var.required_verified_domain == lower(var.required_verified_domain)
      )
    )
    error_message = "required_verified_domain must be null or a lowercase root domain."
  }
}

variable "kms_key_id" {
  description = "Existing AWS KMS key for OpenTofu state and plan encryption."
  type        = string
}

variable "kms_region" {
  description = "Region of the existing OpenTofu state encryption key."
  type        = string
}

variable "kms_key_spec" {
  description = "OpenTofu state encryption key specification."
  type        = string
  default     = "AES_256"
}

data "azuread_domains" "required" {
  count = var.required_verified_domain == null ? 0 : 1

  include_unverified = true
}

locals {
  required_domain = var.required_verified_domain == null ? null : one([
    for domain in data.azuread_domains.required[0].domains : domain
    if domain.domain_name == var.required_verified_domain
  ])
  user_principal_domain = lower(try(split("@", var.user_principal_name)[1], ""))
}

resource "random_password" "initial" {
  length           = 40
  min_lower        = 3
  min_upper        = 3
  min_numeric      = 3
  min_special      = 3
  override_special = "!@#%*-_+="
}

# Creating a regular user supplies an internal Entra credential. This is not an
# invitation, conversion of an existing identity, or a service-license grant.
resource "azuread_user" "this" {
  user_principal_name     = var.user_principal_name
  display_name            = var.display_name
  mail_nickname           = split("@", var.user_principal_name)[0]
  account_enabled         = true
  password                = random_password.initial.result
  force_password_change   = true
  disable_strong_password = false

  lifecycle {
    prevent_destroy = true
    # The user owns the permanent password after their first interactive login.
    ignore_changes = [password, force_password_change]

    precondition {
      condition = (
        var.required_verified_domain == null ||
        local.user_principal_domain == var.required_verified_domain
      )
      error_message = "required_verified_domain must exactly match the user_principal_name domain."
    }

    precondition {
      condition = var.required_verified_domain == null || try(
        local.required_domain["verified"] &&
        local.required_domain["authentication_type"] == "Managed" &&
        local.required_domain["default"] == false &&
        local.required_domain["initial"] == false,
        false
      )
      error_message = "required_verified_domain must be present, verified, managed, non-default and non-initial before creating the user."
    }
  }
}

output "user_principal_name" {
  description = "Pilot sign-in name for private credential handoff."
  value       = azuread_user.this.user_principal_name
  sensitive   = true
}

output "initial_password" {
  description = "One-time bootstrap password; privately hand off, then change interactively before PSSO registration."
  value       = random_password.initial.result
  sensitive   = true
}
