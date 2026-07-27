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

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "platform-storage"
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
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          path           = "clusters/homelab/platform/storage"
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
          "CreateNamespace=false"
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
          value = "automated; verify existing NFS provisioner and backup coverage before relying on PVCs"
        },
        {
          name  = "storage"
          value = "docs/storage-nfs.md"
        }
      ]
    }
  }
}
