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

variable "image_update_handoff" {
  description = "Optional paused image-ownership metadata during a temporary source-edit handoff; does not create a controller resource."
  type        = any
  default     = null

  validation {
    condition = var.image_update_handoff == null ? true : (
      try(var.image_update_handoff.paused == true, false) &&
      !contains(try(keys(var.manifest.spec.source.helm), []), "parameters") &&
      !contains(try(keys(var.manifest.spec.source.kustomize), []), "images") &&
      alltrue([for source in try(var.manifest.spec.sources, []) :
        !contains(try(keys(source.helm), []), "parameters") &&
        !contains(try(keys(source.kustomize), []), "images")
      ])
    )
    error_message = "A temporary image_update_handoff must be paused and must omit configured Helm parameters and Kustomize images; permanent removal uses neither ownership input."
  }
}
