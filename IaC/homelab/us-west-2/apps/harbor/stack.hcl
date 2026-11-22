locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../external-secrets/argocd", "../../cert-manager/argocd", "../../istio/argocd", "../../platform-storage/argocd", "../../prometheus/argocd"]
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
        value = "https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/clusters/homelab/apps/harbor/README.md"
      }
    ]
  }
}
