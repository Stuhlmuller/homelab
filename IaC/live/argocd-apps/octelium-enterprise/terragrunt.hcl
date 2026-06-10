include "root" {
  path = find_in_parent_folders("root.hcl")
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
  metadata = {
    name      = "octelium-enterprise"
    namespace = "argocd"
    labels = {
      "app.kubernetes.io/managed-by" = "terragrunt"
      "app.kubernetes.io/part-of"    = "homelab"
    }
  }

  project = "homelab"

  destination = {
    server    = "https://kubernetes.default.svc"
    namespace = "octelium"
  }

  sources = [
    {
      repo_url        = local.repo_url
      target_revision = local.target_revision
      path            = "clusters/homelab/apps/octelium-enterprise"
      kustomize       = {}
    }
  ]

  sync_policy = {
    automated = {
      prune     = true
      self_heal = true
    }
    sync_options = [
      "CreateNamespace=false",
      "ServerSideApply=true",
      "RespectIgnoreDifferences=true"
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

  ignore_differences = [
    {
      group     = "apps"
      kind      = "Deployment"
      name      = "svc-console-octelium"
      namespace = "octelium"
      jq_path_expressions = [
        ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
      ]
    },
    {
      group     = "apps"
      kind      = "Deployment"
      name      = "svc-dirsync-octelium"
      namespace = "octelium"
      jq_path_expressions = [
        ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
      ]
    },
    {
      group     = "apps"
      kind      = "Deployment"
      name      = "svc-enterprise-octelium-api"
      namespace = "octelium"
      jq_path_expressions = [
        ".spec.template.spec.containers[] | select(.name == \"vigil\" or .name == \"managed\") | .image"
      ]
    },
    {
      group     = "apps"
      kind      = "Deployment"
      name      = "svc-public-octelium"
      namespace = "octelium"
      jq_path_expressions = [
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
