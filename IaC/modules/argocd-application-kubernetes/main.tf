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
  metadata = merge(
    {
      name      = var.metadata.name
      namespace = try(var.metadata.namespace, "argocd")
    },
    length(try(var.metadata.annotations, {})) > 0 ? { annotations = var.metadata.annotations } : {},
    length(try(var.metadata.finalizers, [])) > 0 ? { finalizers = var.metadata.finalizers } : {},
    length(try(var.metadata.labels, {})) > 0 ? { labels = var.metadata.labels } : {}
  )

  destination = {
    name      = try(var.destination.name, null)
    namespace = try(var.destination.namespace, null)
    server    = try(var.destination.server, null)
  }

  computed_fields = var.computed_fields == null ? [] : var.computed_fields

  sources = [
    for source in var.sources : merge(
      { repoURL = source.repo_url },
      try(source.chart, null) != null ? { chart = source.chart } : {},
      try(source.name, null) != null ? { name = source.name } : {},
      try(source.path, null) != null ? { path = source.path } : {},
      try(source.ref, null) != null ? { ref = source.ref } : {},
      try(source.target_revision, null) != null ? { targetRevision = source.target_revision } : {},
      try(source.directory, null) != null ? {
        directory = merge(
          try(source.directory.exclude, null) != null ? { exclude = source.directory.exclude } : {},
          try(source.directory.include, null) != null ? { include = source.directory.include } : {},
          try(source.directory.recurse, null) != null ? { recurse = source.directory.recurse } : {},
          try(source.directory.jsonnet, null) != null ? {
            jsonnet = merge(
              try(source.directory.jsonnet.libs, null) != null ? { libs = source.directory.jsonnet.libs } : {},
              try(length(source.directory.jsonnet.ext_vars), 0) > 0 ? {
                extVars = [
                  for ext_var in source.directory.jsonnet.ext_vars : merge(
                    try(ext_var.code, null) != null ? { code = ext_var.code } : {},
                    try(ext_var.name, null) != null ? { name = ext_var.name } : {},
                    try(ext_var.value, null) != null ? { value = ext_var.value } : {}
                  )
                ]
              } : {},
              try(length(source.directory.jsonnet.tlas), 0) > 0 ? {
                tlas = [
                  for tla in source.directory.jsonnet.tlas : merge(
                    try(tla.code, null) != null ? { code = tla.code } : {},
                    try(tla.name, null) != null ? { name = tla.name } : {},
                    try(tla.value, null) != null ? { value = tla.value } : {}
                  )
                ]
              } : {}
            )
          } : {}
        )
      } : {},
      try(source.helm, null) != null ? {
        helm = merge(
          try(source.helm.ignore_missing_value_files, null) != null ? { ignoreMissingValueFiles = source.helm.ignore_missing_value_files } : {},
          try(source.helm.pass_credentials, null) != null ? { passCredentials = source.helm.pass_credentials } : {},
          try(source.helm.release_name, null) != null ? { releaseName = source.helm.release_name } : {},
          try(source.helm.skip_crds, null) != null ? { skipCrds = source.helm.skip_crds } : {},
          try(source.helm.skip_schema_validation, null) != null ? { skipSchemaValidation = source.helm.skip_schema_validation } : {},
          try(source.helm.value_files, null) != null ? { valueFiles = source.helm.value_files } : {},
          try(source.helm.values, null) != null ? { values = source.helm.values } : {},
          try(source.helm.version, null) != null ? { version = source.helm.version } : {},
          try(length(source.helm.file_parameters), 0) > 0 ? {
            fileParameters = [
              for file_parameter in source.helm.file_parameters : {
                name = file_parameter.name
                path = file_parameter.path
              }
            ]
          } : {},
          try(length(source.helm.parameters), 0) > 0 ? {
            parameters = [
              for parameter in source.helm.parameters : merge(
                { name = parameter.name },
                try(parameter.force_string, null) != null ? { forceString = parameter.force_string } : {},
                try(parameter.value, null) != null ? { value = parameter.value } : {}
              )
            ]
          } : {}
        )
      } : {},
      try(source.kustomize, null) != null ? {
        kustomize = merge(
          try(source.kustomize.common_annotations, null) != null ? { commonAnnotations = source.kustomize.common_annotations } : {},
          try(source.kustomize.common_labels, null) != null ? { commonLabels = source.kustomize.common_labels } : {},
          try(source.kustomize.images, null) != null ? { images = source.kustomize.images } : {},
          try(source.kustomize.name_prefix, null) != null ? { namePrefix = source.kustomize.name_prefix } : {},
          try(source.kustomize.name_suffix, null) != null ? { nameSuffix = source.kustomize.name_suffix } : {},
          try(source.kustomize.version, null) != null ? { version = source.kustomize.version } : {},
          try(length(source.kustomize.patches), 0) > 0 ? {
            patches = [
              for patch in source.kustomize.patches : merge(
                try(patch.options, null) != null ? { options = patch.options } : {},
                try(patch.patch, null) != null ? { patch = patch.patch } : {},
                try(patch.path, null) != null ? { path = patch.path } : {},
                {
                  target = merge(
                    try(patch.target.annotation_selector, null) != null ? { annotationSelector = patch.target.annotation_selector } : {},
                    try(patch.target.group, null) != null ? { group = patch.target.group } : {},
                    try(patch.target.kind, null) != null ? { kind = patch.target.kind } : {},
                    try(patch.target.label_selector, null) != null ? { labelSelector = patch.target.label_selector } : {},
                    try(patch.target.name, null) != null ? { name = patch.target.name } : {},
                    try(patch.target.namespace, null) != null ? { namespace = patch.target.namespace } : {},
                    try(patch.target.version, null) != null ? { version = patch.target.version } : {}
                  )
                }
              )
            ]
          } : {}
        )
      } : {},
      try(source.plugin, null) != null ? {
        plugin = merge(
          try(source.plugin.name, null) != null ? { name = source.plugin.name } : {},
          try(length(source.plugin.env), 0) > 0 ? {
            env = [
              for env_var in source.plugin.env : {
                name  = env_var.name
                value = env_var.value
              }
            ]
          } : {}
        )
      } : {}
    )
  ]

  sync_policy = var.sync_policy == null ? null : merge(
    try(var.sync_policy.automated, null) != null ? {
      automated = {
        allowEmpty = coalesce(try(var.sync_policy.automated.allow_empty, null), false)
        enabled    = coalesce(try(var.sync_policy.automated.enabled, null), true)
        prune      = coalesce(try(var.sync_policy.automated.prune, null), false)
        selfHeal   = coalesce(try(var.sync_policy.automated.self_heal, null), false)
      }
    } : {},
    try(var.sync_policy.managed_namespace_metadata, null) != null ? {
      managedNamespaceMetadata = merge(
        try(var.sync_policy.managed_namespace_metadata.annotations, null) != null ? { annotations = var.sync_policy.managed_namespace_metadata.annotations } : {},
        try(var.sync_policy.managed_namespace_metadata.labels, null) != null ? { labels = var.sync_policy.managed_namespace_metadata.labels } : {}
      )
    } : {},
    try(var.sync_policy.retry, null) != null ? {
      retry = merge(
        try(var.sync_policy.retry.limit, null) != null ? { limit = var.sync_policy.retry.limit } : {},
        try(var.sync_policy.retry.backoff, null) != null ? {
          backoff = merge(
            try(var.sync_policy.retry.backoff.duration, null) != null ? { duration = var.sync_policy.retry.backoff.duration } : {},
            try(var.sync_policy.retry.backoff.factor, null) != null ? { factor = var.sync_policy.retry.backoff.factor } : {},
            try(var.sync_policy.retry.backoff.max_duration, null) != null ? { maxDuration = var.sync_policy.retry.backoff.max_duration } : {}
          )
        } : {}
      )
    } : {},
    try(var.sync_policy.sync_options, null) != null ? { syncOptions = var.sync_policy.sync_options } : {}
  )

  ignore_differences = [
    for ignore_difference in var.ignore_differences : merge(
      try(ignore_difference.group, null) != null ? { group = ignore_difference.group } : {},
      try(ignore_difference.jq_path_expressions, null) != null ? { jqPathExpressions = ignore_difference.jq_path_expressions } : {},
      try(ignore_difference.json_pointers, null) != null ? { jsonPointers = ignore_difference.json_pointers } : {},
      try(ignore_difference.kind, null) != null ? { kind = ignore_difference.kind } : {},
      try(ignore_difference.managed_fields_managers, null) != null ? { managedFieldsManagers = ignore_difference.managed_fields_managers } : {},
      try(ignore_difference.name, null) != null ? { name = ignore_difference.name } : {},
      try(ignore_difference.namespace, null) != null ? { namespace = ignore_difference.namespace } : {}
    )
  ]

  spec = merge(
    {
      project     = var.project
      destination = local.destination
      sources     = local.sources
    },
    var.revision_history_limit != null ? { revisionHistoryLimit = var.revision_history_limit } : {},
    local.sync_policy != null ? { syncPolicy = local.sync_policy } : {},
    length(local.ignore_differences) > 0 ? { ignoreDifferences = local.ignore_differences } : {},
    length(var.info) > 0 ? { info = var.info } : {}
  )

  manifest = {
    apiVersion = var.api_version
    kind       = "Application"
    metadata   = local.metadata
    spec       = local.spec
  }
}

resource "kubernetes_manifest" "this" {
  manifest        = local.manifest
  computed_fields = length(local.computed_fields) > 0 ? local.computed_fields : null

  field_manager {
    force_conflicts = true
    name            = "terragrunt"
  }

  dynamic "wait" {
    for_each = var.manifest_wait != null ? [var.manifest_wait] : []
    content {
      fields  = try(wait.value.fields, null)
      rollout = try(wait.value.rollout, null)

      dynamic "condition" {
        for_each = try(wait.value.conditions, [])
        content {
          status = try(condition.value.status, null)
          type   = try(condition.value.type, null)
        }
      }
    }
  }

  dynamic "timeouts" {
    for_each = var.timeouts != null ? [var.timeouts] : []
    content {
      create = try(timeouts.value.create, null)
      delete = try(timeouts.value.delete, null)
      update = try(timeouts.value.update, null)
    }
  }
}
