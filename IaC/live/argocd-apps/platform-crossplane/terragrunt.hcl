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
  paths = []
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "platform-crossplane"
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
        namespace = "crossplane-system"
      }

      sources = [
        {
          repoURL        = "https://charts.crossplane.io/stable"
          chart          = "crossplane"
          path           = "."
          targetRevision = "2.3.3"
          helm = {
            releaseName = "crossplane"
          }
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
          "ServerSideApply=true",
          "SkipDryRunOnMissingResource=true"
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
          value = "core only; add providers and credentials in purpose-specific changes"
        },
        {
          name  = "docs"
          value = "clusters/homelab/platform/crossplane/README.md"
        }
      ]
    }
  }
}
