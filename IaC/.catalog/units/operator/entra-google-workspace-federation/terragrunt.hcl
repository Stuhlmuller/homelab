include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
}

terraform {
  source = "../../modules/entra-google-workspace-federation"
}

generate "providers" {
  path      = "providers.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.root_config.locals.aws_region}"
}
provider "msgraph" {}
EOF
}

inputs = {
  aws_region              = local.root_config.locals.aws_region
  domain_name             = "stuhlmuller.net"
  metadata_parameter_name = "/homelab/entra/google-workspace-federation-metadata"
}
