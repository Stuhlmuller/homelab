locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "cert-manager", "istio"]
  spec = {
    project = "homelab-workloads"
    destination = {
      namespace = "automation"
    }
    info = [
      {
        name  = "public-webhook"
        value = "Policy Bot UI targets policy-bot.homelab via Octelium; /api/github/hook uses policy-bot-hook.stinkyboi.com through octelium-public"
      }
    ]
  }
}
