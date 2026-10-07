terraform {
  required_version = ">= 1.10.0"

  required_providers {
    msgraph = {
      source  = "microsoft/msgraph"
      version = "0.5.0"
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

variable "owner_object_id" {
  description = "Existing owner's exact object ID from the private reviewed baseline."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.owner_object_id))
    error_message = "owner_object_id must be a lowercase UUID from the existing owner."
  }
}

variable "expected_identities" {
  description = "Complete unchanged Graph identities collection from the private owner baseline."
  type = list(object({
    signInType       = string
    issuer           = string
    issuerAssignedId = optional(string)
  }))
  sensitive = true

  validation {
    condition = (
      length(var.expected_identities) == 2 &&
      length([for identity in var.expected_identities : identity if
        identity.signInType == "federated" && identity.issuer == "MicrosoftAccount" && identity.issuerAssignedId == null
      ]) == 1 &&
      length([for identity in var.expected_identities : identity if
        identity.signInType == "userPrincipalName" && identity.issuerAssignedId == "rodman@stinkyboi.com"
      ]) == 1
    )
    error_message = "The baseline must retain exactly the existing MicrosoftAccount federation and owner UPN identity."
  }
}

variable "expected_current_mail" {
  description = "Exact current Graph mail from the fresh private baseline, including when preparing rollback."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = can(regex("^[^@[:space:]<>\"']+@[^@[:space:]<>\"']+\\.[^@[:space:]<>\"']+$", var.expected_current_mail))
    error_message = "expected_current_mail must be the existing email from the reviewed current owner."
  }
}

variable "replacement_mail" {
  description = "Private, operator-confirmed reachable replacement mail; not an authentication identity change."
  type        = string
  sensitive   = true

  validation {
    condition = (
      can(regex("^[^@[:space:]<>\"']+@[^@[:space:]<>\"']+\\.[^@[:space:]<>\"']+$", var.replacement_mail))
    )
    error_message = "replacement_mail must be an explicit email from the reviewed forward or rollback plan."
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

locals {
  owner_upn    = "rodman@stinkyboi.com"
  owner_fields = "id,userPrincipalName,userType,creationType,externalUserState,accountEnabled,identities"
  owner_exports = {
    id             = "id"
    upn            = "userPrincipalName"
    user_type      = "userType"
    creation_type  = "creationType"
    external_state = "externalUserState"
    enabled        = "accountEnabled"
    identities     = "identities"
  }
  expected_identity_json = toset([for identity in var.expected_identities : jsonencode(identity)])
}

# Read the fixed existing identity; do not adopt/create an azuread_user.
data "msgraph_resource" "owner" {
  url         = "users/${var.owner_object_id}"
  api_version = "v1.0"
  query_parameters = {
    "$select" = ["${local.owner_fields},mail"]
  }
  response_export_values = merge(local.owner_exports, { mail = "mail" })
}

# This resource PATCHes only mail. Graph owns proxy recalculation; it does not
# promise removal of the old SMTP alias. Never proceed straight to pilot rename.
resource "msgraph_update_resource" "mail" {
  url           = "users/${var.owner_object_id}"
  api_version   = "v1.0"
  update_method = "PATCH"
  body          = sensitive({ mail = var.replacement_mail })
  read_query_parameters = {
    "$select" = ["${local.owner_fields},mail"]
  }
  response_export_values  = local.owner_exports
  ignore_missing_property = false

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = try(data.msgraph_resource.owner.output.mail == var.expected_current_mail, false)
      error_message = "Stop: existing owner mail differs from the reviewed current-mail baseline. Refresh and review a new plan."
    }

    precondition {
      condition = try(
        data.msgraph_resource.owner.output.id == var.owner_object_id &&
        data.msgraph_resource.owner.output.upn == local.owner_upn &&
        data.msgraph_resource.owner.output.user_type == "Member" &&
        data.msgraph_resource.owner.output.creation_type == "Invitation" &&
        data.msgraph_resource.owner.output.external_state == "Accepted" &&
        data.msgraph_resource.owner.output.enabled == true &&
        toset([for identity in data.msgraph_resource.owner.output.identities : jsonencode(identity)]) == local.expected_identity_json,
        false,
      )
      error_message = "Stop: existing owner ID, UPN, external identity or enabled state differs from the reviewed baseline."
    }

    postcondition {
      condition = try(
        self.output.id == var.owner_object_id &&
        self.output.upn == local.owner_upn &&
        self.output.user_type == "Member" &&
        self.output.creation_type == "Invitation" &&
        self.output.external_state == "Accepted" &&
        self.output.enabled == true &&
        toset([for identity in self.output.identities : jsonencode(identity)]) == local.expected_identity_json,
        false,
      )
      error_message = "Stop: owner identity changed. Do not release the original email to the pilot."
    }
  }
}
