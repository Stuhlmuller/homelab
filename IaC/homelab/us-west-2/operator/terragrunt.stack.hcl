unit "operator_github_actions_role_policy" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/github-actions-role-policy"
  path                    = "github-actions-role-policy"
  no_dot_terragrunt_stack = true
}

unit "operator_state_bucket_encryption" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/state-bucket-encryption"
  path                    = "state-bucket-encryption"
  no_dot_terragrunt_stack = true
}

unit "operator_etcd_backup_storage" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/etcd-backup-storage"
  path                    = "etcd-backup-storage"
  no_dot_terragrunt_stack = true
}

unit "operator_platform_etcd_reader" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/platform-etcd-reader"
  path                    = "platform-etcd-reader"
  no_dot_terragrunt_stack = true
}

unit "operator_application_backup_storage" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/application-backup-storage"
  path                    = "application-backup-storage"
  no_dot_terragrunt_stack = true
}

unit "operator_azuread_ci_identities" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/azuread-ci-identities"
  path                    = "azuread-ci-identities"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_stuhlmuller_domain" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/entra-stuhlmuller-domain"
  path                    = "entra-stuhlmuller-domain"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_stuhlmuller_pilot_user" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/entra-stuhlmuller-pilot-user"
  path                    = "entra-stuhlmuller-pilot-user"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_google_workspace_federation" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/entra-google-workspace-federation"
  path                    = "entra-google-workspace-federation"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_emergency_global_admin" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/entra-emergency-global-admin"
  path                    = "entra-emergency-global-admin"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_owner_mail" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/entra-owner-mail"
  path                    = "entra-owner-mail"
  no_dot_terragrunt_stack = true
}

unit "operator_tailscale_access" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/operator/tailscale-access"
  path                    = "tailscale-access"
  no_dot_terragrunt_stack = true
}
