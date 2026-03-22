terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/nomad-job?ref=0.1.0"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  jobspec_file = "${dirname(find_in_parent_folders("root.hcl"))}/jobs/nfs-csi-plugin.nomad.hcl"
}
