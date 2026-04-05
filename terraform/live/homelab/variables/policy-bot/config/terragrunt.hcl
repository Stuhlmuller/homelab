terraform {
  source = "../../../../../modules/nomad_variable"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/policy-bot/config"
  items = {
    public_url = "https://policy-bot.stinkyboi.com"
  }
  ssm_parameters = {
    github_app_integration_id  = "/homelab/policy-bot/github_app_integration_id"
    github_app_private_key     = "/homelab/policy-bot/github_app_private_key"
    github_app_webhook_secret  = "/homelab/policy-bot/github_app_webhook_secret"
    github_oauth_client_id     = "/homelab/policy-bot/github_oauth_client_id"
    github_oauth_client_secret = "/homelab/policy-bot/github_oauth_client_secret"
    sessions_key               = "/homelab/policy-bot/sessions_key"
  }
}
