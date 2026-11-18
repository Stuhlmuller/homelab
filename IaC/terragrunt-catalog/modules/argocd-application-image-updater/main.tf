terraform {
  required_version = ">= 1.10"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "3.2.1"
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


locals {
  has_single_source = try(var.manifest.spec.source, null) != null
  sources           = jsondecode(try(var.manifest.spec.sources, null) == null ? "[]" : jsonencode(var.manifest.spec.sources))
  render_source = jsondecode(local.has_single_source ? jsonencode(var.manifest.spec.source) : jsonencode(
    try(local.sources[0], {})
  ))
  render_kind = try(local.render_source.helm, null) != null ? "helm" : "kustomize"

  valid_source_topology = (
    local.has_single_source != (length(local.sources) > 0) &&
    (try(local.render_source.helm, null) != null) != (try(local.render_source.kustomize, null) != null) &&
    try(local.render_source.plugin, null) == null &&
    try(local.render_source.directory, null) == null &&
    try(var.manifest.spec.sourceHydrator, null) == null &&
    alltrue([for source in slice(local.sources, min(1, length(local.sources)), length(local.sources)) :
      try(length(source.ref) > 0, false) &&
      try(source.helm, null) == null && try(source.kustomize, null) == null &&
      try(source.plugin, null) == null && try(source.directory, null) == null &&
      try(source.path, "") == "" && try(source.chart, null) == null
    ])
  )

  helm_parameter_names = flatten([for image in var.image_update.images :
    image.helm == null ? [] : compact([image.helm.name, image.helm.tag, image.helm.spec])
  ])
  kustomize_image_names = [for image in var.image_update.images : image.kustomize.name if image.kustomize != null]
  # Absence is intentional: provider omission preserves controller-only values
  # during a paused default-module handoff. Even an empty configured list changes
  # that state history, so never seed these collections from mutable selectors.
  valid_override_ownership = (
    !contains(try(keys(local.render_source.helm), []), "parameters") &&
    !contains(try(keys(local.render_source.kustomize), []), "images")
  )

  valid_image_targets = (
    length(local.helm_parameter_names) == length(distinct(local.helm_parameter_names)) &&
    length(local.kustomize_image_names) == length(distinct(local.kustomize_image_names)) &&
    alltrue([for image in var.image_update.images :
      local.render_kind == "helm" ? image.helm != null : image.kustomize != null
    ])
  )
  valid_source_paths = alltrue([for image in var.image_update.images :
    alltrue([for path in image.source_paths :
      (try(length(local.render_source.path) > 0, false) && startswith(path, "${try(local.render_source.path, "")}/")) ||
      contains([for file in try(local.render_source.helm.valueFiles, []) : replace(file, "/^\\$[^/]+\\//", "")], path)
    ])
  ])

  default_computed_fields = [
    "metadata.annotations",
    "metadata.labels",
    "spec.destination.name",
  ]
  multi_source_computed_fields = length(local.sources) > 1 ? [
    for idx, source in local.sources : "spec.sources[${idx}].path"
    if(try(source.path, null) == null || try(source.path, null) == ".") && (
      try(source.chart, null) != null ||
      try(source.ref, null) != null ||
      try(source.directory, null) != null
    )
  ] : []
  image_override_path = "${local.has_single_source ? "spec.source" : "spec.sources[0]"}.${local.render_kind == "helm" ? "helm.parameters" : "kustomize.images"}"
  computed_field_defaults = concat(
    local.default_computed_fields, local.multi_source_computed_fields, [local.image_override_path]
  )

  image_updater_manifest = {
    apiVersion = "argocd-image-updater.argoproj.io/v1alpha1"
    kind       = "ImageUpdater"
    metadata = {
      name      = var.manifest.metadata.name
      namespace = "argocd"
    }
    spec = {
      writeBackConfig = { method = "argocd" }
      commonUpdateSettings = {
        updateStrategy = "digest"
        ignoreTags     = var.image_update.paused ? ["*"] : []
      }
      applicationRefs = [{
        namePattern    = var.manifest.metadata.name
        useAnnotations = false
        images = [for image in var.image_update.images : {
          alias     = image.alias
          imageName = image.image_name
          manifestTargets = merge(
            image.helm == null ? {} : { helm = { for key, value in image.helm : key => value if value != null } },
            image.kustomize == null ? {} : { kustomize = image.kustomize }
          )
        }]
      }]
    }
  }
}

resource "kubernetes_manifest" "image_updater" {
  manifest   = local.image_updater_manifest
  depends_on = [kubernetes_manifest.this]

  lifecycle {
    precondition {
      condition     = local.valid_source_topology && local.valid_image_targets && local.valid_override_ownership && local.valid_source_paths
      error_message = "Enrollment requires one matching renderer, absent configured image overrides, unique mapping targets and source_paths inside that source or its value files."
    }
  }

  field_manager {
    name            = "terragrunt-image-enrollment"
    force_conflicts = false
  }
}

# Same root address as the default module: opt-in does not replace Application state.
resource "kubernetes_manifest" "this" {
  manifest        = var.manifest
  computed_fields = local.computed_field_defaults

  lifecycle {
    # These collections are created ONLY by the updater. Configured collections
    # (even empty) are rejected; ordinary options belong in values/valueFiles.
    ignore_changes = [
      manifest["spec"]["source"]["helm"]["parameters"],
      manifest["spec"]["source"]["kustomize"]["images"],
      manifest["spec"]["sources"][0]["helm"]["parameters"],
      manifest["spec"]["sources"][0]["kustomize"]["images"],
    ]
    precondition {
      condition     = local.valid_source_topology && local.valid_image_targets && local.valid_override_ownership && local.valid_source_paths
      error_message = "Enrollment requires one matching renderer, absent configured image overrides, unique mapping targets and source_paths inside that source or its value files."
    }
  }

  field_manager {
    name            = "terragrunt"
    force_conflicts = false
  }
}
