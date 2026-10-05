locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["external-secrets", "istio"]
  spec = {
    destination = {
      namespace = "octelium-client"
    }
    info = [
      {
        name  = "mode"
        value = "Octelium service catalog is the homelab app access path; app FQDNs use private Istio SNI backend routes"
      },
      {
        name  = "services"
        value = "Serves the explicit homelab service catalog in docs/examples/octelium"
      },
      {
        name  = "enterprise"
        value = "Enterprise package octeliumee desired version 0.22.0 is adopted by the octelium-enterprise Argo CD Application"
      },
      {
        name  = "state"
        value = "Stateless connector plus in-cluster demo service"
      }
    ]
  }
}
