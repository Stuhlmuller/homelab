locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "traefik"]
  spec = {
    project = "homelab-workloads"
    destination = {
      namespace = "automation"
    }
  }
}
