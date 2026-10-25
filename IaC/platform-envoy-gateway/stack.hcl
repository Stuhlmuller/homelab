locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["istio", "cert-manager", "platform-gateway-api-crds"]
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
        chart          = "gateway-helm"
        path           = "."
        targetRevision = "v1.9.2"
        helm = {
          releaseName = "envoy-gateway"
          valueFiles  = ["$values/clusters/homelab/platform/envoy-gateway/values.yaml"]
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
      },
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/envoy-gateway"
        targetRevision = local.shared.target_revision
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
        name  = "activation"
        value = "disabled until published images, platform prerequisites, and private route qualification pass"
      },
    ]
  }
}
