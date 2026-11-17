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
  description = "Argo CD Application with one renderer and optional value refs."
  type        = any

  validation {
    condition = (
      try(var.manifest.apiVersion, "") == "argoproj.io/v1alpha1" &&
      try(var.manifest.kind, "") == "Application" &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.manifest.metadata.name)) &&
      try(var.manifest.metadata.namespace, "") == "argocd"
    )
    error_message = "Enrollment requires an exact named Application in the argocd namespace."
  }

}

variable "image_update" {
  description = "Explicit mutable image selectors and their exclusively owned source files. No resolved workload digests are stored here."
  type = object({
    paused = optional(bool, false)
    images = list(object({
      alias        = string
      image_name   = string
      source_paths = set(string)
      helm = optional(object({
        name = optional(string)
        tag  = optional(string)
        spec = optional(string)
      }))
      kustomize = optional(object({ name = string }))
    }))
  })

  validation {
    condition = (
      length(var.image_update.images) > 0 &&
      length(distinct([for image in var.image_update.images : image.alias])) == length(var.image_update.images) &&
      alltrue([for image in var.image_update.images :
        can(regex("^[a-zA-Z0-9][a-zA-Z0-9-._]*$", image.alias)) &&
        can(regex("^[^@[:space:]]+/[^@[:space:]:]+:[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$", image.image_name))
      ])
    )
    error_message = "Provide at least one unique alias and explicit repository:mutable-tag image (no digest or implicit latest)."
  }

  validation {
    condition = alltrue([for image in var.image_update.images :
      length(image.source_paths) > 0 && alltrue([for path in image.source_paths :
        startswith(path, "clusters/homelab/") &&
        !can(regex("(^|/)\\.\\.?(/|$)|[\\\\*?\\[\\]{}]|//", path)) &&
        can(regex("\\.ya?ml$", path))
      ])
    ])
    error_message = "source_paths must be exact clusters/homelab YAML files without traversal, backslashes or glob patterns."
  }

  validation {
    condition = alltrue([for image in var.image_update.images :
      (image.helm != null) != (image.kustomize != null) &&
      (image.helm == null ? true : (
        image.helm.spec != null ? (
          image.helm.spec != "" && image.helm.name == null && image.helm.tag == null
          ) : (
          try(length(image.helm.name) > 0, false) && try(length(image.helm.tag) > 0, false) &&
          image.helm.name != image.helm.tag
        )
      )) &&
      (image.kustomize == null ? true : can(regex("^[^@[:space:]=]+$", image.kustomize.name)))
    ])
    error_message = "Each image needs exactly one explicit Helm spec or name/tag mapping, or a Kustomize image name."
  }


}

variable "image_update_handoff" {
  description = "Temporary maintenance metadata is mutually exclusive with active enrollment."
  type        = any
  default     = null

  validation {
    condition     = var.image_update_handoff == null
    error_message = "Use either image_update or image_update_handoff, never both."
  }
}
