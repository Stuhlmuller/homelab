include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = [
    "../external-secrets",
    "../cert-manager",
    "../istio",
    "../tailscale",
    "../prometheus",
    "../platform-storage"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
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

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "monitoring"
  }

  sources = [
    {
      repo_url        = "https://grafana.github.io/helm-charts"
      chart           = "grafana"
      target_revision = "10.5.15"
      helm = {
        release_name = "grafana"
        value_files  = ["$values/clusters/homelab/apps/grafana/values.yaml"]
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      ref             = "values"
      directory = {
        include = ".argocd-values-ref-placeholder.yaml"
      }
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/grafana"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
    sync_options = [
      "CreateNamespace=true",
      "ServerSideApply=true"
    ]
    retry = {
      limit = "5"
      backoff = {
        duration     = "30s"
        factor       = "2"
        max_duration = "2m"
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
      value = "docs/networking-tailnet-ingress.md"
    }
  ]
}
