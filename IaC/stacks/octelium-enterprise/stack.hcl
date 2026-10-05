locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["octelium-cluster", "octelium-storage"]
  spec = {
    destination = {
      namespace = "octelium"
    }
    syncPolicy = {
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true", "RespectIgnoreDifferences=true"]
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
