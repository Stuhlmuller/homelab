locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "platform-storage", "langfuse"]
  metadata = {
    annotations = {
      "argocd.argoproj.io/compare-options" = "ServerSideDiff=true"
    }
  }
  spec = {
    destination = {
      namespace = "ai"
    }
    sources = [
      {
        repoURL        = "ghcr.io/berriai"
        chart          = "litellm-helm"
        path           = "."
        targetRevision = "0.1.832"
        helm = {
          releaseName = "litellm"
          valueFiles  = ["$values/clusters/homelab/apps/litellm/values.yaml"]
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
        path           = "clusters/homelab/apps/litellm"
        targetRevision = local.shared.target_revision
      }
    ]
    info = [
      {
        name  = "rollout"
        value = "automated; verify provider secrets and NFS backup coverage before exposing the gateway"
      }
    ]
  }
}
