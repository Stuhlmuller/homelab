locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = []
  spec = {
    syncPolicy = {
      automated = {
        allowEmpty = true
      }
      syncOptions = ["ServerSideApply=true"]
    }
  }
}
