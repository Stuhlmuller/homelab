include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/azuread-saml-application"
}

generate "identity_providers" {
  path      = "identity-providers.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
provider "msgraph" {}
EOF
}

inputs = {
  display_name                   = "Fleet Console"
  entity_id                      = "https://fleet.stinkyboi.com"
  assertion_consumer_service_url = "https://fleet.stinkyboi.com/api/v1/fleet/sso/callback"
  login_url                      = "https://fleet.stinkyboi.com/login"
  allowed_user_principal_names   = ["rodman@stinkyboi.com"]
  signing_certificate_end_date   = "2027-10-04T00:00:00Z"
}
