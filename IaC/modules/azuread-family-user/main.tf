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
