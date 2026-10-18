include "root" {
  path = find_in_parent_folders("root.hcl")
}

# A separate signed, reviewed change must opt in after explicit authorization.
# Keep this literal source-controlled: Terragrunt feature flags are runtime-overridable.
locals {
  emergency_global_admin_enabled = false
}

# Keep ordinary direct and run --all applies from creating or removing the
# emergency Global Administrator. Validation and saved-plan review remain available.
exclude {
  if      = !local.emergency_global_admin_enabled
  no_run  = true
  actions = ["apply", "destroy"]
}

terraform {
  source = "../../modules/entra-emergency-global-admin"
}

generate "identity_provider" {
  path      = "identity-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF2
provider "azuread" {}
EOF2
}
