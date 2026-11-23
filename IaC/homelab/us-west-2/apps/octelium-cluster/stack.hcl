locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../istio/argocd", "../../platform-multus/argocd", "../../octelium-storage/argocd"]
  spec = {
    destination = {
      namespace = "istio-system"
    }
    syncPolicy = {
      automated = {
        prune = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
    }
    info = [
      {
        name  = "bootstrap"
        value = "Run scripts/octelium-cluster-bootstrap.sh after platform-multus and octelium-storage are healthy"
      }
    ]
  }
}
