locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets"]
  spec = {
    sources = [
      {
        repoURL        = "https://charts.jetstack.io"
        chart          = "cert-manager"
        path           = "."
        targetRevision = "v1.20.3"
        helm = {
          releaseName = "cert-manager"
          valueFiles  = ["$values/clusters/homelab/apps/cert-manager/values-v1.20.3.yaml"]
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
      },
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/apps/cert-manager"
        targetRevision = local.shared.target_revision
      }
    ]
  }
}
