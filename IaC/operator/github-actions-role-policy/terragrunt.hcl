include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  aws_region  = local.root_config.locals.aws_region
}

terraform {
  source = "../../modules/aws-github-actions-role-policy"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"
}
EOF
}

inputs = {
  apply_role_name                     = "Github-TF-State"
  parameter_reader_group_name         = "homelab-ssm-parameter-readers"
  parameter_reader_policy_name_prefix = "homelab-ssm-parameter-reader-"
  parameter_reader_policy_slot_count  = 10
  policy_name                         = "homelab-github-terragrunt-ssm-reader-policy-admin"
}
