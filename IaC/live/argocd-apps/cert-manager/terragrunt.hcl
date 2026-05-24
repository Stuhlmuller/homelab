include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "argocd_provider" {
  path = find_in_parent_folders("argocd-provider.hcl")
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/argocd-application?ref=415f4ec587846f6928aeb344cd9e46f66c16a005"
}

dependencies {
  paths = ["../external-secrets"]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "cert-manager"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "default"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "cert-manager"
  }

  sources = [
    {
      repo_url        = "https://charts.jetstack.io"
      chart           = "cert-manager"
      target_revision = "v1.19.2"
      helm = {
        release_name = "cert-manager"
        value_files  = ["$values/clusters/homelab/apps/cert-manager/values.yaml"]
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
      path            = "clusters/homelab/apps/cert-manager"
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
}
