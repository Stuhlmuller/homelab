include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/entra-verified-family-user"
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
  display_name             = "Rodman Mac (stuhlmuller.net pilot)"
  required_verified_domain = "stuhlmuller.net"
}
