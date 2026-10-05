locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = []
  spec = {
    destination = {
      namespace = "argocd"
    }
    syncPolicy = {
      automated = {
        allowEmpty = true
      }
    }
    info = [
      {
        name  = "purpose"
        value = "retirement tombstone; Renovate owns repository image updates"
      }
    ]
  }
}
