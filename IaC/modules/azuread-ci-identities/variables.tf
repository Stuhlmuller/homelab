variable "operator_object_id" {
  description = "Immutable object ID of the human tenant owner who retains sole ownership of both CI identities."
  type        = string

  validation {
    condition     = var.operator_object_id == "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
    error_message = "This bootstrap is restricted to the declared human tenant owner object."
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
