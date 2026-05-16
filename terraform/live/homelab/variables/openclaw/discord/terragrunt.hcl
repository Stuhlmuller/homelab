terraform {
  source = "../../../../../modules/nomad_variable"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/openclaw/discord"
  ssm_parameters = {
    bot_token = "/homelab/openclaw/discord_bot_token"
  }
}
