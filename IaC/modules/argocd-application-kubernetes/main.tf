terraform {
  required_version = ">= 1.10"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0"
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

removed {
  from = argocd_application.this

  lifecycle {
    destroy = false
  }
}

locals {
  sources = try(var.manifest.spec.sources, [])

  default_computed_fields = [
    "metadata.annotations",
    "metadata.labels",
    "spec.destination.name",
  ]
  multi_source_computed_fields = length(local.sources) > 1 ? [
    # Argo CD normalizes default paths for multi-source chart, ref, and
    # directory entries. Keep only that API-owned field computed so revision
    # pins and every other repository-owned source field remain declarative.
    for idx, source in local.sources : "spec.sources[${idx}].path"
    if contains([null, "."], try(source.path, null)) && (
      try(source.chart, null) != null ||
      try(source.ref, null) != null ||
      try(source.directory, null) != null
    )
  ] : []
  computed_field_defaults = concat(local.default_computed_fields, local.multi_source_computed_fields)
  computed_fields         = var.computed_fields == null ? local.computed_field_defaults : distinct(concat(local.computed_field_defaults, var.computed_fields))
}

resource "kubernetes_manifest" "this" {
  manifest        = var.manifest
  computed_fields = length(local.computed_fields) > 0 ? local.computed_fields : null

  field_manager {
    force_conflicts = true
    name            = "terragrunt"
  }
}
