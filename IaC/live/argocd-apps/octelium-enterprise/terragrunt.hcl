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
    "../octelium-cluster",
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
      name      = "octelium-enterprise"
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
        namespace = "octelium"
      }

      sources = [
        {
          repoURL        = local.repo_url
          targetRevision = local.target_revision
          path           = "clusters/homelab/apps/octelium-enterprise"
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
          "CreateNamespace=false",
          "ServerSideApply=true",
          "RespectIgnoreDifferences=true"
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
          kind      = "Deployment"
          name      = "svc-console-octelium"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        },
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-dirsync-octelium"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        },
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-enterprise-octelium-api"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        },
        {
          group     = "apps"
          kind      = "Deployment"
          name      = "svc-public-octelium"
          namespace = "octelium"
          jqPathExpressions = [
            ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
          ]
        }
      ]

      info = [
        {
          name  = "package"
          value = "Octelium Enterprise package octeliumee 0.22.0"
        },
        {
          name  = "ownership"
          value = "Argo CD owns the package Kubernetes steady state after octops installation"
        },
        {
          name  = "state"
          value = "Enterprise stores use octelium-rscstore, octelium-logstore, and octelium-metricstore PVCs"
        }
      ]
    }
  }
}
