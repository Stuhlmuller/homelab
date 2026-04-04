locals {
  project_name   = "homelab"
  nomad_addr     = get_env("NOMAD_ADDR", "http://10.1.0.200:4646")
  kms_key_id     = get_env("TG_KMS_KEY_ID", "alias/homelab-opentofu")
  state_bucket   = get_env("TG_STATE_BUCKET", "rstuhlmuller-aws-s3-use1-datalake")
  state_key_root = get_env("TG_STATE_KEY_ROOT", "homelab")
  state_region   = get_env("TG_STATE_REGION", "us-east-1")
  aws_region     = get_env("TG_AWS_REGION", local.state_region)

  default_tags = {
    ManualBuild = false
    ManualTags  = false
    Owner       = "themanofrod"
    Project     = "homelab"
  }
}

terraform {
  extra_arguments "plan" {
    commands  = ["plan"]
    arguments = ["-out", "plan.out"]
  }
}

generate "nomad_provider" {
  path      = "nomad_provider.tf"
  if_exists = "overwrite"
  contents  = <<EOF
provider "nomad" {
  address = "${local.nomad_addr}"
}
EOF
}

generate "aws_provider" {
  path      = "aws_provider.tf"
  if_exists = "overwrite"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"
}
EOF
}

remote_state {
  backend = "s3"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }
  config = {
    bucket       = local.state_bucket
    encrypt      = true
    key          = "${local.state_key_root}/${path_relative_to_include()}/terraform.tfstate"
    region       = local.state_region
    use_lockfile = true
  }
}

inputs = {
  project_name = local.project_name
  tags         = local.default_tags
  kms_key_id   = local.kms_key_id
  aws_region   = local.aws_region
}
