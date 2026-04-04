terraform {
  source = "../../../../../modules/nomad_variable"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/traefik/cf_dns_api_token"
  ssm_parameters = {
    cf_dns_api_token = "/homelab/traefik/cf_dns_api_token"
  }
}
