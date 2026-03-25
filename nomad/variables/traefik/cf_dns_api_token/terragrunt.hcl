
terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/nomad-variable?ref=0.2.0"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/traefik/cf_dns_api_token"

  items = {
    # Cloudflare API token with Zone:DNS:Edit permission for Let's Encrypt DNS-01 challenge.
    # Generate one at https://dash.cloudflare.com/profile/api-tokens
    cf_dns_api_token = "REPLACE_ME"
  }
}
