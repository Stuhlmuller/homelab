include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

locals {
  stack_values = jsondecode(read_tfvars_file("terragrunt.values.hcl"))
  defaults     = local.stack_values.defaults
  name         = basename(get_terragrunt_dir())
  metadata     = try(local.stack_values.metadata, {})
  spec         = try(local.stack_values.spec, {})
  sync_policy  = try(local.spec.syncPolicy, {})
  retry        = try(local.sync_policy.retry, {})

  # Merge the common CRD maps explicitly. Lists (sources, syncOptions, info,
  # ignoreDifferences) replace defaults; they must never be concatenated.
  manifest = merge(local.defaults.manifest, {
    metadata = merge(local.defaults.manifest.metadata, { name = local.name }, local.metadata, {
      labels = merge(local.defaults.manifest.metadata.labels, try(local.metadata.labels, {}))
    })
    spec = merge(local.defaults.manifest.spec, {
      sources = [{
        repoURL        = local.defaults.repo_url
        targetRevision = local.defaults.target_revision
        path           = "${local.defaults.source_root}/${local.name}"
      }]
      }, local.spec, {
      destination = merge(local.defaults.manifest.spec.destination, { namespace = local.name }, try(local.spec.destination, {}))
      syncPolicy = merge(local.defaults.manifest.spec.syncPolicy, local.sync_policy, {
        automated = merge(local.defaults.manifest.spec.syncPolicy.automated, try(local.sync_policy.automated, {}))
        retry = merge(local.defaults.manifest.spec.syncPolicy.retry, local.retry, {
          backoff = merge(local.defaults.manifest.spec.syncPolicy.retry.backoff, try(local.retry.backoff, {}))
        })
      })
    })
  })
}

dependencies {
  paths = [
    for dependency in try(local.stack_values.dependencies, []) :
    "${get_terragrunt_dir()}/../${dependency}"
  ]
}

inputs = {
  manifest = local.manifest
}
