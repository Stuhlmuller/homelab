locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["istio", "platform-gateway-api-crds"]
  spec = {
    destination = {
      namespace = "istio-egress"
    }
    sources = [
      {
        repoURL        = local.shared.repo_url
        path           = "clusters/homelab/platform/istio-egress"
        targetRevision = local.shared.target_revision
      }
    ]
    syncPolicy = {
      automated = {
        enabled = false
        prune   = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "activation"
        value = "disabled until Gateway API CRDs, waypoint readiness, and LiteLLM allow/deny traffic are verified"
      }
    ]
  }
}
