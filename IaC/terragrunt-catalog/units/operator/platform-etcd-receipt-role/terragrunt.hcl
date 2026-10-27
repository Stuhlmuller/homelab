include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/aws-platform-etcd-receipt-role"
}

locals {
  source      = read_terragrunt_config("${get_repo_root()}/IaC/etcd-backup-storage.hcl").inputs
  destination = read_terragrunt_config("${get_repo_root()}/IaC/application-backup-storage.hcl").inputs
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region              = "${local.source.region}"
  allowed_account_ids = ["${local.source.account_id}"]
}
EOF
}

inputs = {
  account_id     = local.source.account_id
  region         = local.source.region
  etcd_bucket    = local.source.bucket
  receipt_bucket = local.destination.bucket
  tags = merge(include.root.locals.default_tags, {
    Name    = "homelab-platform-etcd-receipt-publisher"
    Purpose = "etcd-offsite-prerequisite"
  })
}
