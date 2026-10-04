# This is a user, not an application. Reuse the existing AzureAD CI stack so
# validation, reviewed plans and post-merge apply include the identity unit.
include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/azuread-family-user"
}

generate "identity_provider" {
  path      = "identity-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
EOF
}

inputs = {
  user_principal_name = "rodman.mac@stinkyboi.com"
  display_name        = "Rodman Mac"
}
