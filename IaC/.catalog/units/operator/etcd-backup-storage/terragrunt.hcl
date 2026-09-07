include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

terraform {
  source = "../../modules/aws-backup-bucket"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["716182248480"]
}
EOF
}

inputs = {
  bucket_name         = "homelab-etcd-backups-716182248480-us-east-1"
  expected_account_id = "716182248480"
  aws_region          = "us-east-1"
  tags = merge(include.root.locals.default_tags, {
    Name    = "homelab-etcd-backups"
    Purpose = "etcd-offsite-backup"
  })
}
