locals {
  project_name = "homelab"
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

generate "nomad_provider" {
  path      = "nomad_provider.tf"
  if_exists = "overwrite"
  contents  = <<EOF
provider "nomad" {
  address = "http://10.1.0.200:4646"
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
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

catalog {
  urls = [
    "https://github.com/Stuhlmuller/terragrunt-catalog"
  ]
}

inputs = {
  project_name = local.project_name
  tags         = local.default_tags
  kms_key_id   = "959539ca-5646-435c-8ae4-aec13b0f0607" # tofu-encryption-key
}
