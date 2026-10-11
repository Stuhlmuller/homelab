variable "display_name" {
  description = "Enterprise application's human-readable name."
  type        = string
}

variable "owner_user_principal_names" {
  description = "Stable human application owners, independent of the Terraform login."
  type        = set(string)

  validation {
    condition     = length(var.owner_user_principal_names) > 0
    error_message = "Retain at least one explicitly named human application owner."
  }
}

variable "owner_service_principal_names" {
  description = "Explicit automation owners; use unique enterprise-application display names."
  type        = set(string)
  default     = []
}

variable "entity_id" {
  description = "HTTPS SAML entity ID, matching the service provider configuration."
  type        = string

  validation {
    condition     = can(regex("^https://[^/]+", var.entity_id))
    error_message = "entity_id must use HTTPS."
  }
}

variable "assertion_consumer_service_url" {
  description = "Exact HTTPS endpoint receiving the SAML response."
  type        = string

  validation {
    condition     = can(regex("^https://[^/]+/", var.assertion_consumer_service_url))
    error_message = "assertion_consumer_service_url must use HTTPS."
  }
}

variable "login_url" {
  description = "Service-provider initiated login page; avoids unsolicited IdP-initiated login."
  type        = string
}

variable "allowed_user_principal_names" {
  description = "Individually assigned Entra users; group assignment requires a paid Entra license."
  type        = set(string)

  validation {
    condition = length(var.allowed_user_principal_names) > 0 && alltrue([
      for upn in var.allowed_user_principal_names : can(regex("^[^@[:space:]]+@[^@[:space:]]+$", upn))
    ])
    error_message = "At least one explicit Entra user principal name is required."
  }
}

variable "signing_certificate_end_date" {
  description = "Reviewed RFC3339 expiry; update through a PR before certificate expiry."
  type        = string

  validation {
    condition     = can(timecmp(var.signing_certificate_end_date, "2000-01-01T00:00:00Z"))
    error_message = "signing_certificate_end_date must be an RFC3339 timestamp."
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
