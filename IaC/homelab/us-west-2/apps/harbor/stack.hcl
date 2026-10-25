locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "prometheus"]
  spec = {
    sources = [
      {
        repoURL        = "https://helm.goharbor.io"
        chart          = "harbor"
        path           = "."
        targetRevision = "1.19.2"
        helm = {
          releaseName = "harbor"
          valueFiles  = ["$values/clusters/homelab/apps/harbor/values.yaml"]
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
        path           = "clusters/homelab/apps/harbor"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      retry = {
        limit = 5
        backoff = {
          factor      = 2
          maxDuration = "3m"
        }
      }
    }
    info = [
      {
        name  = "url"
        value = "https://harbor.stinkyboi.com"
      },
      {
        name  = "runbook"
        value = "clusters/homelab/apps/harbor/README.md"
      }
    ]
  }
}
