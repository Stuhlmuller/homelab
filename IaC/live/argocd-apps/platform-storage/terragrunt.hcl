include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/argocd-application?ref=415f4ec587846f6928aeb344cd9e46f66c16a005"
}

dependencies {
  paths = []
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "platform-storage"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "default"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "kube-system"
  }

  sources = [
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/platform/storage"
      kustomize       = {}
    }
  ]

  sync_policy = {
    sync_options = [
      "CreateNamespace=false"
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
      value = "manual until existing NFS provisioner and backup coverage are documented"
    },
    {
      name  = "storage"
      value = "docs/storage-nfs.md"
    }
  ]
}

