unit "argocd_apps_fleet" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/argocd-app"
  path                    = "argocd"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}

unit "azuread_applications_fleet" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/azuread-applications/fleet"
  path                    = "azuread"
  no_dot_terragrunt_stack = true
}

unit "azuread_fleet_pilot_user" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/azuread-applications/fleet-pilot-user"
  path                    = "pilot-user"
  no_dot_terragrunt_stack = true
}
