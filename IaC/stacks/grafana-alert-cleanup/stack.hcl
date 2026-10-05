locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "istio"]
  spec = {
    destination = {
      namespace = "monitoring"
    }
    syncPolicy = {
      automated = {
        allowEmpty = true
      }
      syncOptions = ["ServerSideApply=true"]
    }
    info = [
      {
        name  = "purpose"
        value = "retirement tombstone that prunes the completed Grafana alert cleanup resources"
      }
    ]
  }
}
