locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["prometheus"]
  spec = {
    destination = {
      namespace = "kube-system"
    }
    sources = [
      {
        repoURL        = "https://kubernetes-sigs.github.io/descheduler"
        chart          = "descheduler"
        path           = "."
        targetRevision = "0.33.0"
        helm = {
          releaseName = "descheduler"
          valueFiles  = ["$values/clusters/homelab/apps/descheduler/values.yaml"]
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "."
        targetRevision = local.shared.target_revision
        ref            = "values"
        directory = {
          include = ".argocd-values-ref-placeholder.yaml"
        }
      }
    ]
    syncPolicy = {
      syncOptions = ["ServerSideApply=true"]
    }
  }
}
