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
    "../prometheus",
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
      name      = "grafana"
      namespace = "argocd"
      annotations = {
        "argocd.argoproj.io/refresh" = "hard"
      }
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
        namespace = "monitoring"
      }

      sources = [
        {
          repoURL        = "https://grafana.github.io/helm-charts"
          chart          = "grafana"
          path           = "."
          targetRevision = "10.5.15"
          helm = {
            releaseName = "grafana"
            valueFiles  = ["$values/clusters/homelab/apps/grafana/values.yaml"]
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
          path           = "clusters/homelab/apps/grafana"
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
          name  = "alerting-reconcile"
          value = "2026-05-30: tracking main again and bumped the pod annotation to reload alerting provisioning"
        },
        {
          name  = "rollout"
          value = "automated; verify Prometheus and NFS backup coverage before relying on dashboards"
        },
        {
          name  = "ingress"
          value = "private app access is through the Octelium service catalog with Istio SNI backend routing"
        }
      ]
    }
  }
}
