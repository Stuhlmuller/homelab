include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/aws-oci-signing-key"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF_PROVIDER
provider "aws" {
  region = "us-west-2"
}
EOF_PROVIDER
}

inputs = {
  signer_role_name = "Github-TF-State"
}
