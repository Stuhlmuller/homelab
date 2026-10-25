locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["istio", "cert-manager"]
  metadata = {
    annotations = {
      "argocd.argoproj.io/compare-options" = "ServerSideDiff=true"
    }
  }
  spec = {
    destination = {
      namespace = "envoy-gateway-system"
    }
    sources = [
      {
        repoURL        = "docker.io/envoyproxy"
        chart          = "gateway-crds-helm"
        path           = "."
        targetRevision = "v1.9.2"
        helm = {
          releaseName = "envoy-gateway-crds"
          valueFiles  = ["$values/clusters/homelab/platform/envoy-gateway/crds-values.yaml"]
        }
      },
      {
        repoURL        = local.shared.repo_url
        path           = "."
        targetRevision = local.shared.target_revision
        ref            = "values"
        directory = {
          include = ".argocd-values-ref-placeholder.yaml"
        }
      }
    ]
    syncPolicy = {
      automated = {
        enabled = false
        prune   = false
      }
      syncOptions = ["CreateNamespace=true", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "ownership"
        value = "sole owner of Gateway API and Envoy Gateway CRDs; do not prune before dependents retire"
      }
    ]
  }
}
