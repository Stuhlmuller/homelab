include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/aws-s3-bucket-encryption"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "us-east-1"
}
EOF
}

inputs = {
  bucket_name        = "rstuhlmuller-aws-s3-use1-datalake"
  default_kms_key_id = "arn:aws:kms:us-east-1:716182248480:alias/aws/s3"
  bucket_key_enabled = true
}
