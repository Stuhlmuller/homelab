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
  app_defaults = read_terragrunt_config(find_in_parent_folders("defaults.hcl")).locals
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "affine"
      namespace = "argocd"
      labels = {
        "app.kubernetes.io/managed-by" = "terragrunt"
        "app.kubernetes.io/part-of"    = "homelab"
      }
    }

    spec = {
      project = "homelab"

      destination = {
        name      = ""
        server    = "https://kubernetes.default.svc"
        namespace = "affine"
      }

      sources = [
        {
          repoURL        = local.app_defaults.repo_url
          targetRevision = local.app_defaults.target_revision
          path           = "clusters/homelab/apps/affine"
          kustomize      = {}
        }
      ]

      syncPolicy = {
        automated = {
          allowEmpty = false
          enabled    = true
          prune      = true
          selfHeal   = true
        }
        syncOptions = [
          "CreateNamespace=true",
          "ServerSideApply=true"
        ]
        retry = {
          limit = "5"
          backoff = {
            duration    = "30s"
            factor      = "2"
            maxDuration = "3m"
          }
        }
      }

      ignoreDifferences = [
        {
          group     = "apps"
          kind      = "StatefulSet"
          name      = "affine-postgres"
          namespace = "affine"
          jsonPointers = [
            "/metadata/annotations",
            "/spec/volumeClaimTemplates"
          ]
        },
        {
          group     = "apps"
          kind      = "StatefulSet"
          name      = "affine-redis"
          namespace = "affine"
          jsonPointers = [
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
  }
}
