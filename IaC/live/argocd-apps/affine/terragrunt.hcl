include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = [
    "../external-secrets",
    "../cert-manager",
    "../istio",
    "../octelium",
    "../octelium-public",
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "affine"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "affine"
  }

  sources = [
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/affine"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      enabled   = true
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
        max_duration = "3m"
      }
    }
  }

  ignore_differences = [
    {
      group     = "apps"
      kind      = "StatefulSet"
      name      = "affine-postgres"
      namespace = "affine"
      json_pointers = [
        "/metadata/annotations",
        "/spec/volumeClaimTemplates"
      ]
    },
    {
      group     = "apps"
      kind      = "StatefulSet"
      name      = "affine-redis"
      namespace = "affine"
      json_pointers = [
        "/metadata/annotations",
        "/spec/volumeClaimTemplates"
      ]
    }
  ]

  info = [
    {
      name  = "url"
      value = "https://affine.stinkyboi.com"
    },
    {
      name  = "rollout"
      value = "automated after generated SSM secrets, External Secrets, pgvector PostgreSQL, Redis, NFS, Istio, and Octelium are healthy"
    },
    {
      name  = "storage"
      value = "docs/storage-nfs.md"
    }
  ]
}
