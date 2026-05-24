include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/argocd-application?ref=415f4ec587846f6928aeb344cd9e46f66c16a005"
}

dependencies {
  paths = [
    "../external-secrets",
    "../cert-manager",
    "../istio",
    "../tailscale",
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "litellm"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "default"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "ai"
  }

  sources = [
    {
      repo_url        = "ghcr.io/berriai"
      chart           = "litellm-helm"
      target_revision = "0.1.832"
      helm = {
        release_name = "litellm"
        value_files  = ["$values/clusters/homelab/apps/litellm/values.yaml"]
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      ref             = "values"
      path            = ""
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/litellm"
      kustomize       = {}
    }
  ]

  sync_policy = {
    sync_options = [
      "CreateNamespace=true",
      "ServerSideApply=true"
    ]
    retry = {
      limit = "5"
      backoff = {
        duration     = "30s"
        factor       = "2"
        max_duration = "2m"
      }
    }
  }

  info = [
    {
      name  = "rollout"
      value = "manual until provider secrets and NFS backup coverage are ready"
    }
  ]
}
