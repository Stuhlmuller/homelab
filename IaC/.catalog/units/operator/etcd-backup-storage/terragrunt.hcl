include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

terraform {
  source = "../../modules/aws-backup-bucket"
}

locals {
  destination = jsondecode(file("${get_repo_root()}/IaC/config/etcd-backup-storage.json"))
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
  bucket_name         = local.destination.bucket
  expected_account_id = local.destination.account_id
  aws_region          = local.destination.region
  tags = merge(include.root.locals.default_tags, {
    Name    = "homelab-etcd-backups"
    Purpose = "etcd-offsite-backup"
  })
}
