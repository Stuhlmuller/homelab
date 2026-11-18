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
    if(try(source.path, null) == null || try(source.path, null) == ".") && (
      try(source.chart, null) != null ||
      try(source.ref, null) != null ||
      try(source.directory, null) != null
    )
  ] : []
  computed_field_defaults = concat(local.default_computed_fields, local.multi_source_computed_fields)
}

resource "kubernetes_manifest" "this" {
  manifest        = var.manifest
  computed_fields = local.computed_field_defaults

  field_manager {
    force_conflicts = true
    name            = "terragrunt"
  }
}
