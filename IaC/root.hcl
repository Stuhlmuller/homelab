locals {
  project_name = "homelab"
  aws_region   = "us-west-2"
  state_region = "us-east-1"
  kms_key_id   = "alias/homelab-opentofu"
  # Existing OpenTofu state encryption follows the current S3 backend region.
  kms_region             = local.state_region
  kms_key_spec           = "AES_256"
  kubernetes_config_path = "~/.kube/config"
  default_tags = {
    ManualBuild = false
    ManualTags  = false
    Project     = "homelab"
    Owner       = "Stuhlmuller"
  }
}

terraform {
  extra_arguments "plan" {
    commands  = ["plan"]
    arguments = ["-out", "plan.out"]
  }
}

generate "providers" {
  path      = "providers.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "kubernetes" {
  config_path = pathexpand("${local.kubernetes_config_path}")
}

provider "helm" {
  kubernetes = {
    config_path = pathexpand("${local.kubernetes_config_path}")
  }
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
    bucket       = "rstuhlmuller-aws-s3-use1-datalake"
    key          = "IaC/${lower(local.project_name)}/${path_relative_to_include()}/terraform.tfstate"
    region       = local.state_region
    encrypt      = true
    kms_key_id   = local.kms_key_id
    use_lockfile = true
  }
}

catalog {
  urls = [
    "https://github.com/Stuhlmuller/terragrunt-catalog"
  ]
}

inputs = {
  project_name           = local.project_name
  tags                   = local.default_tags
  aws_region             = local.aws_region
  kms_key_id             = local.kms_key_id
  kms_region             = local.kms_region
  kms_key_spec           = local.kms_key_spec
  kubernetes_config_path = local.kubernetes_config_path
}
