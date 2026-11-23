terragrunt_version_constraint = ">= 1.2.2"

locals {
  project_name       = read_terragrunt_config(find_in_parent_folders("account.hcl", "${get_repo_root()}/IaC/homelab/account.hcl")).locals.account_name
  aws_region         = read_terragrunt_config(find_in_parent_folders("region.hcl", "${get_repo_root()}/IaC/homelab/us-west-2/region.hcl")).locals.aws_region
  state_region       = "us-east-1"
  kms_key_id         = "alias/homelab-opentofu"
  runtime_kms_key_id = "alias/aws/ssm"
  # Existing OpenTofu state encryption follows the current S3 backend region.
  kms_region             = local.state_region
  kms_key_spec           = "AES_256"
  kubernetes_config_path = "~/.kube/config"
  default_tags           = read_terragrunt_config(find_in_parent_folders("account.hcl", "${get_repo_root()}/IaC/homelab/account.hcl")).locals.default_tags
  # Remove each exception after the declared apply verifies an encrypted state write.
  legacy_state_units = [
    "homelab/us-west-2/apps/langfuse/blob-storage",
    "homelab/us-west-2/operator/application-backup-storage",
    "homelab/us-west-2/operator/entra-google-workspace-federation",
    "homelab/us-west-2/operator/etcd-backup-storage",
    "homelab/us-west-2/operator/github-actions-role-policy",
    "homelab/us-west-2/operator/state-bucket-encryption",
    "homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth",
  ]
}

remote_state {
  backend = "s3"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }
  # Keep the persisted provider identity used by the former module policies.
  encryption = merge({
    key_provider             = "aws_kms"
    kms_key_id               = local.kms_key_id
    region                   = local.kms_region
    key_spec                 = local.kms_key_spec
    encrypted_metadata_alias = "key_provider.aws_kms.main"
    }, jsondecode(
    lower(local.project_name) == "homelab" && contains(local.legacy_state_units, path_relative_to_include()) ? jsonencode({
      fallback = { method = "unencrypted" }
    }) : jsonencode({ enforced = true })
  ))
  config = {
    bucket = "rstuhlmuller-aws-s3-use1-datalake"
    key = "IaC/${lower(local.project_name)}/${startswith(path_relative_to_include(), "homelab/us-west-2/apps/") ? lookup({
      "homelab/us-west-2/apps/fleet/azuread"         = "live/azuread-applications/fleet"
      "homelab/us-west-2/apps/fleet/pilot-user"      = "live/azuread-applications/fleet-pilot-user"
      "homelab/us-west-2/apps/grafana/azuread"       = "live/azuread-applications/grafana"
      "homelab/us-west-2/apps/octelium/azuread"      = "live/azuread-applications/octelium"
      "homelab/us-west-2/apps/langfuse/blob-storage" = "live/langfuse-blob-storage"
    }, path_relative_to_include(), length(split("/", path_relative_to_include())) == 5 && endswith(path_relative_to_include(), "/argocd") ? "live/argocd-apps/${split("/", path_relative_to_include())[3]}" : path_relative_to_include()) : startswith(path_relative_to_include(), "homelab/us-west-2/shared/") ? "live/${replace(path_relative_to_include(), "homelab/us-west-2/shared/", "")}" : replace(path_relative_to_include(), "homelab/us-west-2/", "")}/terraform.tfstate"
    region       = local.state_region
    encrypt      = true
    kms_key_id   = local.kms_key_id
    use_lockfile = true
  }
}

catalog {
  urls = [
    "${get_repo_root()}/IaC/terragrunt-catalog",
    "https://github.com/Stuhlmuller/terragrunt-catalog"
  ]
}

terraform {
  before_hook "verify_current_main_before_apply" {
    commands = ["apply"]
    execute  = ["bash", "${get_parent_terragrunt_dir()}/../scripts/ci/terragrunt-current-main.sh"]
  }
}

inputs = {}
