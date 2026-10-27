locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults = local.shared.argocd_defaults
  dependencies = [
    "../aws-ssm-parameters",
    "external-secrets",
    "cert-manager",
    "platform-storage"
  ]
  spec = {
    project = "openclaw-enterprise"
    destination = {
      namespace = "openclaw-system"
    }
    syncPolicy = {
      automated = {
        enabled  = false
        prune    = false
        selfHeal = false
      }
      syncOptions = ["CreateNamespace=false", "ServerSideApply=true"]
      retry = {
        limit = 0
      }
    }
    info = [
      {
        name  = "activation"
        value = "manual full sync only after storage, secret and capacity gates; 15 minute operation timeout"
      }
    ]
  }
}
