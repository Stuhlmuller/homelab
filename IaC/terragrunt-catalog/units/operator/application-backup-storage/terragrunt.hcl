include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/aws-backup-bucket"
}

locals {
  destination = read_terragrunt_config("${get_repo_root()}/IaC/application-backup-storage.hcl").inputs
  etcd_source = read_terragrunt_config("${get_repo_root()}/IaC/etcd-backup-storage.hcl").inputs
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
  # Reserved for a future reviewed publisher. No workflow assumes this role.
  publisher = {
    role_name     = "homelab-oce-recovery-publisher"
    object_prefix = "openclaw-enterprise/new/"
    subject       = "repo:Stuhlmuller/homelab:environment:homelab-production"
    workflow      = "OpenClaw Enterprise Recovery Publication"
    ref           = "refs/heads/main"
    repository_id = 973476220
  }
  platform_receipt_publisher = {
    role_name     = "homelab-platform-receipt-publisher"
    source_bucket = local.etcd_source.bucket
    subject       = "repo:Stuhlmuller/homelab:environment:homelab-production"
    workflow      = "Platform Recovery Receipt Publication"
    ref           = "refs/heads/main"
    repository_id = 973476220
  }
  tags = merge(include.root.locals.default_tags, {
    Name    = "homelab-application-backups"
    Purpose = "application-offsite-backup"
  })
}
