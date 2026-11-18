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
    "../../octelium-public/argocd",
    "../../platform-storage/argocd"
  ]
  spec = {
    info = [
      {
        name  = "url"
        value = "https://mastodon.stinkyboi.com"
      },
      {
        name  = "runbook"
        value = "clusters/homelab/apps/mastodon/README.md"
      }
    ]
  }
}
