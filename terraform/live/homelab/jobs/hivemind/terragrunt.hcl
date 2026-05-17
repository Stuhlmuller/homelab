terraform {
  source = "../../../../modules/nomad_job"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

dependencies {
  paths = ["../../volumes/shared-data"]
}

inputs = {
  jobspec_file     = "${dirname(find_in_parent_folders("root.hcl"))}/../nomad/jobs/hivemind/job.nomad.hcl"
  purge_on_destroy = true
  rerun_if_dead    = true

  timeouts = {
    create = "15m"
    update = "15m"
  }
}
