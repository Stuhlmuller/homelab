terraform {
  source = "../../../../../modules/nomad_variable"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  path = "nomad/jobs/dokploy/config"
  items = {
    root_domain = "homelab.local"
    server_ip   = "10.1.0.200"
  }
  ssm_parameters = {
    postgres_password = "/homelab/dokploy/postgres_password"
  }
}
