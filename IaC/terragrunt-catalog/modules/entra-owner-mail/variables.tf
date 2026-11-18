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
