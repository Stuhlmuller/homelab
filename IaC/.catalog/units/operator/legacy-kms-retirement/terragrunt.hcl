include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/aws-kms-key-retirement"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region              = "us-west-2"
  allowed_account_ids = ["716182248480"]
}
EOF
}

inputs = {
  account_id           = "716182248480"
  key_id               = "959539ca-5646-435c-8ae4-aec13b0f0607"
  alias_name           = "alias/tofu-encryption-key"
  retirement_requested = true
}
