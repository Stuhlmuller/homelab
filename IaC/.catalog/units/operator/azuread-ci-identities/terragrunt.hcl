include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/azuread-ci-identities"
}

generate "azuread_provider" {
  path      = "azuread-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
EOF
}

inputs = {
  operator_user_principal_name = "rodman@stinkyboi.com"
}
