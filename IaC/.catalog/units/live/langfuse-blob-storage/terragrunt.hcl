include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  destination = jsondecode(file("${get_repo_root()}/IaC/config/langfuse-blob-storage.json"))
}

terraform {
  source = "../../modules/aws-langfuse-blob-storage"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region              = "${local.destination.region}"
  allowed_account_ids = ["${local.destination.account_id}"]
}
EOF
}

inputs = {
  bucket_name          = local.destination.bucket
  expected_account_id  = local.destination.account_id
  aws_region           = local.destination.region
  parameter_kms_key_id = local.root_config.locals.runtime_kms_key_id
  tags = merge(local.root_config.locals.default_tags, {
    Name    = "homelab-langfuse-raw-events"
    Purpose = "langfuse-raw-event-storage"
  })
}
