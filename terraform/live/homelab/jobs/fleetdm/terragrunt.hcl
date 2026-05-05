terraform {
  source = "../../../../modules/nomad_job"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

dependencies {
  paths = ["../../variables/fleetdm/config"]
}

inputs = {
  jobspec_file     = "${dirname(find_in_parent_folders("root.hcl"))}/../nomad/jobs/fleetdm/job.nomad.hcl"
  purge_on_destroy = true
  rerun_if_dead    = true
  timeouts = {
    create = "25m"
    update = "25m"
  }
}
