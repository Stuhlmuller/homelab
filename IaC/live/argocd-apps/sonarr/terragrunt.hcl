include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = [
    "../cert-manager",
    "../istio",
    "../deluge",
    "../media-postgres",
    "../prowlarr",
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "sonarr"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "media"
  }

  sources = [
    {
      repo_url        = "https://bjw-s-labs.github.io/helm-charts"
      chart           = "app-template"
      target_revision = "4.4.0"
      helm = {
        release_name = "sonarr"
        value_files  = ["$values/clusters/homelab/apps/sonarr/values.yaml"]
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
      path            = "clusters/homelab/apps/sonarr"
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
      name  = "rollout"
      value = "automated; verify Deluge, Prowlarr, and NFS backup coverage before relying on media automation"
    }
  ]
}
