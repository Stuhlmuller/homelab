locals {
  project_name       = read_terragrunt_config("${get_repo_root()}/IaC/homelab/account.hcl").locals.account_name
  aws_region         = read_terragrunt_config("${get_repo_root()}/IaC/homelab/us-west-2/region.hcl").locals.aws_region
  state_region       = "us-east-1"
  kms_key_id         = "alias/homelab-opentofu"
  runtime_kms_key_id = "alias/aws/ssm"
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

remote_state {
  backend = "s3"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }
  config = {
    bucket = "rstuhlmuller-aws-s3-use1-datalake"
    key = "IaC/${lower(local.project_name)}/${startswith(path_relative_to_include(), "homelab/us-west-2/apps/") ? lookup({
      "homelab/us-west-2/apps/fleet/azuread"         = "live/azuread-applications/fleet"
      "homelab/us-west-2/apps/fleet/pilot-user"      = "live/azuread-applications/fleet-pilot-user"
      "homelab/us-west-2/apps/grafana/azuread"       = "live/azuread-applications/grafana"
      "homelab/us-west-2/apps/octelium/azuread"      = "live/azuread-applications/octelium"
      "homelab/us-west-2/apps/langfuse/blob-storage" = "live/langfuse-blob-storage"
    }, path_relative_to_include(), "live/argocd-apps/${split("/", path_relative_to_include())[3]}") : startswith(path_relative_to_include(), "homelab/us-west-2/shared/") ? "live/${replace(path_relative_to_include(), "homelab/us-west-2/shared/", "")}" : replace(path_relative_to_include(), "homelab/us-west-2/", "")}/terraform.tfstate"
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

terraform {
  before_hook "verify_current_main_before_apply" {
    commands = ["apply"]
    execute  = ["bash", "${get_parent_terragrunt_dir()}/../scripts/ci/terragrunt-current-main.sh"]
  }
}

inputs = {
  project_name = local.project_name
  tags         = local.default_tags
  aws_region   = local.aws_region
  kms_key_id   = local.kms_key_id
  kms_region   = local.kms_region
  kms_key_spec = local.kms_key_spec
}
