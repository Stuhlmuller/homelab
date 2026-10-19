variable "kms_key_id" {
  description = "AWS KMS key ID for OpenTofu state encryption"
  type        = string
}

variable "kms_region" {
  description = "AWS region for the KMS key used by OpenTofu state encryption"
  type        = string
  default     = "us-west-2"
}

variable "kms_key_spec" {
  description = "AWS KMS key spec for OpenTofu state encryption"
  type        = string
  default     = "AES_256"
}

variable "manifest" {
  description = "Raw Argo CD Application manifest"
  type        = any

  validation {
    condition     = try(var.manifest.apiVersion, null) == "argoproj.io/v1alpha1" && try(var.manifest.kind, null) == "Application"
    error_message = "manifest must be an argoproj.io/v1alpha1 Application."
  }
}

variable "computed_fields" {
  description = "Additional manifest field paths that may be changed by the API server or admission controllers"
  type        = list(string)
  default     = null
}
