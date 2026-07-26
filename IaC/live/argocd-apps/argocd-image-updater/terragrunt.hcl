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
  paths = ["../external-secrets"]
}

locals {
  app_defaults = read_terragrunt_config(find_in_parent_folders("defaults.hcl")).locals
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "argocd-image-updater"
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
        namespace = "argocd"
      }

      sources = [
        {
          repoURL        = "https://argoproj.github.io/argo-helm"
          chart          = "argocd-image-updater"
          path           = "."
          targetRevision = "1.2.2"
          helm = {
            releaseName = "argocd-image-updater"
            valueFiles  = ["$values/clusters/homelab/apps/argocd-image-updater/values.yaml"]
          }
        },
        {
          repoURL        = local.app_defaults.repo_url
          targetRevision = local.app_defaults.target_revision
          ref            = "values"
          path           = "."
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.app_defaults.repo_url
          targetRevision = local.app_defaults.target_revision
          path           = "clusters/homelab/apps/argocd-image-updater"
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

      info = [
        {
          name  = "image-updates"
          value = "docs/argocd-image-updater.md"
        }
      ]
    }
  }
}
