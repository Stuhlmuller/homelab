include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/entra-owner-mail"
}

generate "msgraph_provider" {
  path      = "msgraph-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "msgraph" {}
EOF
}

# This temporary unit removes the retired mail-only Graph resource from state
# without calling Graph. It accepts no private owner-mail inputs.
