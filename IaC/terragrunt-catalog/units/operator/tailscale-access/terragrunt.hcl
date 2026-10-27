include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/tailscale-access"
}

generate "tailscale_provider_federated" {
  path      = "tailscale-provider.tf"
  if_exists = "overwrite_terragrunt"
  condition = get_env("TS_IDENTITY_TOKEN") != ""
  contents  = <<EOF
# Authenticate with the Tailscale TF provider using workload identity federation (OIDC).
# In GitHub Actions, the TS_IDENTITY_TOKEN is a short-lived GitHub OIDC JWT exchanged
# for a Tailscale API token by the provider. No client secret is required.
provider "tailscale" {
  oauth_client_id = var.tailscale_oauth_client_id
  identity_token  = "${get_env("TS_IDENTITY_TOKEN")}"
  tailnet         = var.tailscale_tailnet
}
EOF
}

generate "tailscale_provider_api_key" {
  path      = "tailscale-provider.tf"
  if_exists = "overwrite_terragrunt"
  condition = get_env("TS_IDENTITY_TOKEN") == "" && get_env("TS_API_KEY") != ""
  contents  = <<EOF
# Authenticate with the Tailscale TF provider using a Tailscale API key
# tied to your actual Tailscale login (not an OAuth client).
# Used for one-time bootstrap to create federated identities before CI can use OIDC.
provider "tailscale" {
  api_key = "${get_env("TS_API_KEY")}"
  tailnet = var.tailscale_tailnet
}
EOF
}

inputs = {
  # Generation 2 exists in encrypted state since 2026-10-14 UTC; rotate 60 days after provider creation.
  ci_key_generation         = 2
  policy                    = file("${dirname(find_in_parent_folders("root.hcl"))}/../scripts/config/tailscale-policy.json")
  tailscale_oauth_client_id = get_env("TS_OAUTH_CLIENT_ID")
  tailscale_tailnet         = "tail67beb.ts.net"
}
