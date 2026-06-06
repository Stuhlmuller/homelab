include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = [
    "../external-secrets",
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "octelium-storage"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "octelium-storage"
  }

  sources = [
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/octelium-storage"
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

  ignore_differences = [
    {
      group     = "apps"
      kind      = "StatefulSet"
      name      = "octelium-postgres"
      namespace = "octelium-storage"
      json_pointers = [
        "/metadata/annotations",
        "/spec/volumeClaimTemplates"
      ]
    },
    {
      group     = "apps"
      kind      = "StatefulSet"
      name      = "octelium-redis"
      namespace = "octelium-storage"
      json_pointers = [
        "/metadata/annotations",
        "/spec/volumeClaimTemplates"
      ]
    }
  ]

  info = [
    {
      name  = "state"
      value = "PostgreSQL and Redis backing stores for octops init"
    }
  ]
}
