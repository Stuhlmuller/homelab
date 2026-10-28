include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/aws-platform-etcd-reader"
}

locals {
  destination = read_terragrunt_config("${get_repo_root()}/IaC/etcd-backup-storage.hcl").inputs
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
  expected_account_id = local.destination.account_id
  aws_region          = local.destination.region
  bucket_name         = local.destination.bucket
  tags = merge(include.root.locals.default_tags, {
    Name    = "homelab-platform-etcd-reader"
    Purpose = "protected-platform-recovery-read"
  })
}
