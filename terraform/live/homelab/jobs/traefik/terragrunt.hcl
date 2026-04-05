terraform {
  source = "../../../../modules/nomad_job"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

dependencies {
  paths = [
    "../../variables/traefik/cf_dns_api_token",
    "../../volumes/shared-data",
  ]
}

inputs = {
  jobspec_file = "${dirname(find_in_parent_folders("root.hcl"))}/../nomad/jobs/traefik/job.nomad.hcl"
}
