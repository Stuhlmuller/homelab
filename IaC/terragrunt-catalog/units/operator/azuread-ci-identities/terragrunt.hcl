include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/azuread-ci-identities"
}

generate "azuread_provider" {
  path      = "azuread-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
EOF
}

inputs = {
  operator_object_id = "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
}
