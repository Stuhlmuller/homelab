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
  paths = ["../prometheus"]
}

locals {
  app_defaults = read_terragrunt_config(find_in_parent_folders("defaults.hcl")).locals
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "descheduler"
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
        namespace = "kube-system"
      }

      sources = [
        {
          repoURL        = "https://kubernetes-sigs.github.io/descheduler"
          chart          = "descheduler"
          path           = "."
          targetRevision = "0.33.0"
          helm = {
            releaseName = "descheduler"
            valueFiles  = ["$values/clusters/homelab/apps/descheduler/values.yaml"]
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
          path           = "clusters/homelab/apps/descheduler"
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
    }
  }
}
