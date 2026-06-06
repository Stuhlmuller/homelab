include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

dependencies {
  paths = [
    "../external-secrets",
    "../istio"
  ]
}

locals {
  repo_url        = "https://github.com/Stuhlmuller/homelab.git"
  target_revision = "main"
}

inputs = {
  metadata = {
    name      = "octelium"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "octelium-client"
  }

  sources = [
    {
      repo_url        = "ghcr.io/octelium/helm-charts"
      chart           = "octelium"
      target_revision = "0.3.0"
      helm = {
        release_name = "octelium-client"
        value_files  = ["$values/clusters/homelab/apps/octelium/values.yaml"]
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
      path            = "clusters/homelab/apps/octelium"
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
      name  = "mode"
      value = "Octelium client connector target for homelab app access; Tailscale app routes remain fallback until e2e passes"
    },
    {
      name  = "services"
      value = "Serves the explicit homelab service catalog in docs/examples/octelium"
    },
    {
      name  = "enterprise"
      value = "Enterprise package octeliumee desired version 0.22.0 is installed with scripts/octelium-enterprise-package.sh"
    },
    {
      name  = "state"
      value = "Stateless connector plus in-cluster demo service"
    }
  ]
}
