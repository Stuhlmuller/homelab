locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio", "litellm", "platform-storage"]
  spec = {
    destination = {
      namespace = "ai"
    }
    sources = [
      {
        repoURL        = "ghcr.io/multica-ai/charts"
        chart          = "multica"
        path           = "."
        targetRevision = "0.4.29"
        helm = {
          releaseName = "multica"
          valueFiles  = ["$values/clusters/homelab/apps/multica/values.yaml"]
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
        path           = "clusters/homelab/apps/multica"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      retry = {
        backoff = {
          maxDuration = "3m"
        }
      }
    }
    info = [
      {
        name  = "url"
        value = "https://multica.stinkyboi.com"
      },
      {
        name  = "rollout"
        value = "automated after generated SSM secrets, External Secrets, pgvector PostgreSQL, NFS, Istio, and Octelium are healthy"
      },
      {
        name  = "storage"
        value = "docs/storage-nfs.md"
      }
    ]
  }
}
