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
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "litellm"
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
        namespace = "ai"
      }

      sources = [
        {
          repoURL        = "ghcr.io/berriai"
          chart          = "litellm-helm"
          path           = "."
          targetRevision = "0.1.832"
          helm = {
            releaseName = "litellm"
            valueFiles  = ["$values/clusters/homelab/apps/litellm/values.yaml"]
          }
        },
        {
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          ref            = "values"
          path           = "."
          directory = {
            include = ".argocd-values-ref-placeholder.yaml"
          }
        },
        {
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          path           = "clusters/homelab/apps/litellm"
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
          name  = "rollout"
          value = "automated; verify provider secrets and NFS backup coverage before exposing the gateway"
        }
      ]
    }
  }
}
