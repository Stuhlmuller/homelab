terraform {
  source = "../../../../modules/nomad_job"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  jobspec_file = "${dirname(find_in_parent_folders("root.hcl"))}/../nomad/jobs/nfs-csi-plugin/job.nomad.hcl"
}
