include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config   = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  aws_region    = local.root_config.locals.aws_region
  kms_key_id    = local.root_config.locals.runtime_kms_key_id
  state_region  = local.root_config.locals.state_region
  backup_bucket = read_terragrunt_config("${get_repo_root()}/IaC/application-backup-storage.hcl").inputs.bucket
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/aws-github-actions-role-policy"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"
}

provider "aws" {
  alias  = "state"
  region = "${local.state_region}"
}
EOF
}

inputs = {
  apply_role_name    = "Github-TF-State"
  plan_role_name     = "Github-TF-Plan"
  state_bucket_name  = local.root_config.remote_state.config.bucket
  state_kms_key_id   = local.root_config.locals.kms_key_id
  backup_bucket_name = local.backup_bucket

  # checkov:skip=CKV_SECRET_6: These are public IAM resource names, not credential material.
  external_secrets_boundary_policy_name = "homelab-external-secrets-ssm-boundary"
  external_secrets_user_name            = "external-secrets_aws-ssm-auth"
  kms_key_id                            = local.kms_key_id
  parameter_reader_group_name           = "homelab-ssm-parameter-readers"
  parameter_reader_policy_name_prefix   = "homelab-ssm-parameter-reader-"
  parameter_reader_policy_slot_count    = 10
  policy_name                           = "homelab-github-terragrunt-ssm-reader-policy-admin"
}
