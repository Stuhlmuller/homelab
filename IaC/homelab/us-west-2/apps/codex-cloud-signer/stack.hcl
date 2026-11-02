locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "tailscale", "traefik", "platform-storage"]
  spec = {
    project = "homelab-workloads"
    syncPolicy = {
      automated = {
        enabled = false
      }
    }
    destination = {
      namespace = "automation"
    }
  }
}
