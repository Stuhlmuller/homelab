variable "operator_user_principal_name" {
  description = "Existing human tenant owner who retains sole ownership of both CI identities."
  type        = string

  validation {
    condition     = var.operator_user_principal_name == "rodman@stinkyboi.com"
    error_message = "This bootstrap is restricted to the existing rodman@stinkyboi.com tenant owner."
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
