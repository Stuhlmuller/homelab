unit "argocd_apps_octelium" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/argocd-app"
  path                    = "argocd"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}

unit "azuread_applications_octelium" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/azuread-applications/octelium"
  path                    = "azuread"
  no_dot_terragrunt_stack = true
}
