# This is a user, not an application. Reuse the existing AzureAD CI stack so
# validation, reviewed plans and post-merge apply include the identity unit.
include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/azuread-family-user"
}

generate "identity_provider" {
  path      = "identity-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
EOF
}

locals {
  values = jsondecode(read_tfvars_file("terragrunt.values.hcl"))
}

inputs = local.values
