locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults = local.shared.argocd_defaults
  dependencies = [
    "../aws-ssm-parameters",
    "external-secrets",
    "cert-manager",
    "istio",
    "octelium",
    "octelium-public",
    "platform-storage"
  ]
  spec = {
    syncPolicy = {
      retry = {
        backoff = {
          maxDuration = "3m"
        }
      }
    }
    info = [
      {
        name  = "url"
        value = "https://fleet.stinkyboi.com"
      },
      {
        name  = "rollout"
        value = "generated SSM secrets, External Secrets, MySQL, Redis, NFS, Istio, and public device ingress must be healthy before enrollment"
      },
      {
        name  = "storage"
        value = "clusters/homelab/apps/fleet/README.md"
      }
    ]
  }
}
