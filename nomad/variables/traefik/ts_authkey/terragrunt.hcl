
terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/nomad-variable?ref=0.2.0"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/traefik/ts_authkey"

  items = {
    # Replace with a real Tailscale auth key before applying.
    # Generate one at https://login.tailscale.com/admin/settings/keys
    ts_authkey = "REPLACE_ME"
  }
}
