variable "domain_name" {
  description = "Existing Entra custom domain to read and verify."
  type        = string

  validation {
    condition = (
      can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.domain_name)) &&
      var.domain_name == lower(var.domain_name)
    )
    error_message = "domain_name must be a lowercase root domain."
  }
}

variable "verify_domain" {
  description = "POST the one-time Entra verification action after the DNS owner has published and verified the returned TXT record."
  type        = bool
  default     = false
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
