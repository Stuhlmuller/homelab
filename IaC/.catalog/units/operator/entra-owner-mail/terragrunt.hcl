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

# Owner identity and replacement mail come from a private, explicitly supplied
# -var-file, never Terragrunt inputs, environment variables, or public source.
