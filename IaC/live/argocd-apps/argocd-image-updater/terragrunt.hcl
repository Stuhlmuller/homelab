include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
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
    name      = "argocd-image-updater"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "default"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "argocd"
  }

  sources = [
    {
      repo_url        = "https://argoproj.github.io/argo-helm"
      chart           = "argocd-image-updater"
      target_revision = "1.2.2"
      helm = {
        release_name = "argocd-image-updater"
        value_files  = ["$values/clusters/homelab/apps/argocd-image-updater/values.yaml"]
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      ref             = "values"
      directory = {
        include = ".argocd-values-ref-placeholder.yaml"
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/argocd-image-updater"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
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
      name  = "image-updates"
      value = "docs/argocd-image-updater.md"
    }
  ]
}
