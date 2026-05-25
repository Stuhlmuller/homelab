include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = ["../prometheus"]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "descheduler"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "kube-system"
  }

  sources = [
    {
      repo_url        = "https://kubernetes-sigs.github.io/descheduler"
      chart           = "descheduler"
      target_revision = "0.33.0"
      helm = {
        release_name = "descheduler"
        value_files  = ["$values/clusters/homelab/apps/descheduler/values.yaml"]
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
      path            = "clusters/homelab/apps/descheduler"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
    sync_options = [
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
