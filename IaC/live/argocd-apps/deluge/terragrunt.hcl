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
      name      = "deluge"
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
        namespace = "media"
      }

      sources = [
        {
          repoURL        = "https://bjw-s-labs.github.io/helm-charts"
          chart          = "app-template"
          path           = "."
          targetRevision = "4.4.0"
          helm = {
            releaseName = "deluge"
            valueFiles  = ["$values/clusters/homelab/apps/deluge/values.yaml"]
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
          path           = "clusters/homelab/apps/deluge"
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
          value = "automated; verify NFS backup coverage before relying on downloads"
        }
      ]
    }
  }
}
