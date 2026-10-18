locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../aws-ssm-parameters", "external-secrets", "platform-storage"]
  spec = {
    project = "homelab-workloads"
    destination = {
      namespace = "automation"
    }
  }
}
