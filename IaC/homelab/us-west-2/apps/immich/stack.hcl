locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults = local.shared.argocd_defaults
  dependencies = [
    "../../../shared/aws-ssm-parameters",
    "../../external-secrets/argocd",
    "../../istio/argocd",
    "../../platform-storage/argocd",
    "../../traefik/argocd",
    "../../tailnet-dns/argocd"
  ]
  spec = {
    info = [{
      name  = "url"
      value = "https://immich.stinkyboi.com"
    }]
  }
}
