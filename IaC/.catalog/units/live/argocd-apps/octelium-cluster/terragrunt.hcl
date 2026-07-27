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
    "../istio",
    "../platform-multus",
    "../octelium-storage"
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
      name      = "octelium-cluster"
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
        namespace = "istio-system"
      }

      sources = [
        {
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          path           = "clusters/homelab/apps/octelium-cluster"
          kustomize      = {}
        }
      ]

      syncPolicy = {
        automated = {
          allowEmpty = false
          enabled    = true
          prune      = false
          selfHeal   = true
        }
        syncOptions = [
          "CreateNamespace=false",
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
          name  = "bootstrap"
          value = "Run scripts/octelium-cluster-bootstrap.sh after platform-multus and octelium-storage are healthy"
        }
      ]
    }
  }
}
