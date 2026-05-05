terraform {
  source = "../../../../../modules/nomad_variable"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/fleetdm/config"
  items = {
    license_key = ""
    public_url  = "https://fleet.stinkyboi.com"
  }
  ssm_parameters = {
    mysql_password      = "/homelab/fleetdm/mysql_password"
    mysql_root_password = "/homelab/fleetdm/mysql_root_password"
    server_private_key  = "/homelab/fleetdm/server_private_key"
  }
}
