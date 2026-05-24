include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/argocd-application?ref=415f4ec587846f6928aeb344cd9e46f66c16a005"
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
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "default"

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
    },
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/grafana"
      kustomize       = {}
    }
  ]

  sync_policy = {
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
      name  = "rollout"
      value = "manual until Prometheus and NFS backup coverage are ready"
    },
    {
      name  = "ingress"
      value = "docs/networking-tailnet-ingress.md"
    }
  ]
}

