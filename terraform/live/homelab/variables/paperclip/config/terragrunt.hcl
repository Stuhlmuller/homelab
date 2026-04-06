terraform {
  source = "../../../../../modules/nomad_variable"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/paperclip/config"
  items = {
    deployment_mode     = "authenticated"
    deployment_exposure = "public"
    public_url          = "https://paperclip.stinkyboi.com"
  }
  ssm_parameters = {
    better_auth_secret = "/homelab/paperclip/better_auth_secret"
    openrouter_api_key = "/homelab/paperclip/openrouter_api_key"
    postgres_password  = "/homelab/paperclip/postgres_password"
  }
}
