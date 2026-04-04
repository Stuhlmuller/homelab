terraform {
  source = "../../../../modules/nomad_job"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

dependencies {
  paths = [
    "../../variables/dokploy/config",
    "../../volumes/shared-data",
  ]
}

inputs = {
  jobspec_file     = "${dirname(find_in_parent_folders("root.hcl"))}/../nomad/jobs/dokploy/job.nomad.hcl"
  purge_on_destroy = true
  rerun_if_dead    = true
}
