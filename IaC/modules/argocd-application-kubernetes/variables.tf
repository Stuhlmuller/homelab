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

variable "api_version" {
  description = "Argo CD Application API version"
  type        = string
  default     = "argoproj.io/v1alpha1"
}

variable "metadata" {
  description = "Application Kubernetes metadata"
  type = object({
    annotations = optional(map(string), {})
    finalizers  = optional(list(string), [])
    labels      = optional(map(string), {})
    name        = string
    namespace   = optional(string, "argocd")
  })
}

variable "project" {
  description = "Argo CD project for the application"
  type        = string
  default     = "default"
}

variable "destination" {
  description = "Application destination cluster and namespace"
  type = object({
    name      = optional(string)
    namespace = optional(string)
    server    = optional(string)
  })

  validation {
    condition     = try(var.destination.name, null) != null || try(var.destination.server, null) != null
    error_message = "destination must set either name or server."
  }
}

variable "sources" {
  description = "Application manifest or chart sources. Use multiple entries for Argo CD multi-source applications"
  type = list(object({
    chart           = optional(string)
    name            = optional(string)
    path            = optional(string)
    ref             = optional(string)
    repo_url        = string
    target_revision = optional(string)

    directory = optional(object({
      exclude = optional(string)
      include = optional(string)
      recurse = optional(bool)
      jsonnet = optional(object({
        libs = optional(list(string))
        ext_vars = optional(list(object({
          code  = optional(bool)
          name  = optional(string)
          value = optional(string)
        })), [])
        tlas = optional(list(object({
          code  = optional(bool)
          name  = optional(string)
          value = optional(string)
        })), [])
      }))
    }))

    helm = optional(object({
      file_parameters = optional(list(object({
        name = string
        path = string
      })), [])
      ignore_missing_value_files = optional(bool)
      parameters = optional(list(object({
        force_string = optional(bool)
        name         = string
        value        = optional(string)
      })), [])
      pass_credentials       = optional(bool)
      release_name           = optional(string)
      skip_crds              = optional(bool)
      skip_schema_validation = optional(bool)
      value_files            = optional(list(string))
      values                 = optional(string)
      version                = optional(string)
    }))

    kustomize = optional(object({
      common_annotations = optional(map(string))
      common_labels      = optional(map(string))
      images             = optional(list(string))
      name_prefix        = optional(string)
      name_suffix        = optional(string)
      patches = optional(list(object({
        options = optional(map(bool))
        patch   = optional(string)
        path    = optional(string)
        target = object({
          annotation_selector = optional(string)
          group               = optional(string)
          kind                = optional(string)
          label_selector      = optional(string)
          name                = optional(string)
          namespace           = optional(string)
          version             = optional(string)
        })
      })), [])
      version = optional(string)
    }))

    plugin = optional(object({
      env = optional(list(object({
        name  = string
        value = string
      })), [])
      name = optional(string)
    }))
  }))
}

variable "revision_history_limit" {
  description = "Number of revision history entries to retain"
  type        = number
  default     = null
}

variable "sync_policy" {
  description = "Application sync policy"
  type = object({
    automated = optional(object({
      allow_empty = optional(bool)
      enabled     = optional(bool)
      prune       = optional(bool)
      self_heal   = optional(bool)
    }))
    managed_namespace_metadata = optional(object({
      annotations = optional(map(string))
      labels      = optional(map(string))
    }))
    retry = optional(object({
      limit = optional(string)
      backoff = optional(object({
        duration     = optional(string)
        factor       = optional(string)
        max_duration = optional(string)
      }))
    }))
    sync_options = optional(list(string))
  })
  default = null
}

variable "ignore_differences" {
  description = "Resources and fields Argo CD should ignore during diffing"
  type = list(object({
    group                   = optional(string)
    jq_path_expressions     = optional(list(string))
    json_pointers           = optional(list(string))
    kind                    = optional(string)
    managed_fields_managers = optional(list(string))
    name                    = optional(string)
    namespace               = optional(string)
  }))
  default = []
}

variable "info" {
  description = "Informational name/value pairs shown by Argo CD"
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "computed_fields" {
  description = "Manifest field paths that may be changed by the API server or admission controllers"
  type        = list(string)
  default     = null
}

variable "manifest_wait" {
  description = "Wait configuration for Application fields, conditions, or rollout completion"
  type = object({
    fields  = optional(map(string))
    rollout = optional(bool)
    conditions = optional(list(object({
      status = optional(string)
      type   = optional(string)
    })), [])
  })
  default = null
}

variable "timeouts" {
  description = "Timeout configuration for manifest operations"
  type = object({
    create = optional(string)
    delete = optional(string)
    update = optional(string)
  })
  default = null
}
