locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults = local.shared.argocd_defaults
  dependencies = [
    "../../../shared/aws-ssm-parameters",
    "../../external-secrets/argocd",
    "../../cert-manager/argocd",
    "../../istio/argocd",
    "../../octelium/argocd",
    "../../octelium-public/argocd",
    "../../platform-storage/argocd"
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
        value = "https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/clusters/homelab/apps/fleet/README.md"
      }
    ]
  }
}
