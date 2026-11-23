include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/entra-domain-attestation"
}

generate "msgraph_provider" {
  path      = "msgraph-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "msgraph" {}
EOF
}

inputs = {
  domain_name = "stuhlmuller.net"
}
