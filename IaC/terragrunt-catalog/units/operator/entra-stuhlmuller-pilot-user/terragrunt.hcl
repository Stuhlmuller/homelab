include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/entra-retained-mac-pilot"
}

generate "identity_provider" {
  path      = "identity-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
EOF
}

inputs = {
  user_principal_name      = "rodman.mac@stuhlmuller.net"
  pilot_object_id          = "81988711-6241-4fb2-9123-2b885de75dc3"
  required_verified_domain = "stuhlmuller.net"
}
