include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/azuread-saml-application"
}

generate "identity_providers" {
  path      = "identity-providers.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
provider "msgraph" {}
EOF
}

locals {
  values = jsondecode(read_tfvars_file("terragrunt.values.hcl"))
}

inputs = local.values
