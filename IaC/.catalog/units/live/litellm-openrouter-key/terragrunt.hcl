include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
}

terraform {
  source = "../../modules/openrouter-ssm-key"
}

dependencies {
  paths = ["../aws-ssm-parameters"]
}

generate "providers" {
  path      = "providers.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF_PROVIDER
provider "aws" {
  region = "${local.root_config.locals.aws_region}"
}

# OPENROUTER_MANAGEMENT_KEY is injected only by the protected CI workflow.
provider "openrouter" {}
EOF_PROVIDER
}

inputs = {
  key_name       = "homelab-litellm"
  parameter_name = "/homelab/litellm/openrouter-api-key"
  kms_key_id     = local.root_config.locals.runtime_kms_key_id
}
