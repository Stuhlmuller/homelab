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
      name      = "octelium-storage"
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
        namespace = "octelium-storage"
      }

      sources = [
        {
          repoURL        = local.app_defaults.repo_url
          targetRevision = local.app_defaults.target_revision
          path           = "clusters/homelab/apps/octelium-storage"
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
            maxDuration = "2m"
          }
        }
      }

      ignoreDifferences = [
        {
          group     = "apps"
          kind      = "StatefulSet"
          name      = "octelium-postgres"
          namespace = "octelium-storage"
          jsonPointers = [
            "/metadata/annotations",
            "/spec/volumeClaimTemplates"
          ]
        },
        {
          group     = "apps"
          kind      = "StatefulSet"
          name      = "octelium-redis"
          namespace = "octelium-storage"
          jsonPointers = [
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
  }
}
