include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/tailscale-access"
}

generate "tailscale_provider" {
  path      = "tailscale-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "tailscale" {
  oauth_client_id     = "file:${pathexpand("~/.config/homelab/tailscale/terragrunt-oauth-client-id")}"
  oauth_client_secret = "file:${pathexpand("~/.config/homelab/tailscale/terragrunt-oauth-client-secret")}"
}

# Keep ordinary operator reads working after the short-lived owner key is
# removed. The existing OAuth client cannot create OAuth clients or webhooks.
locals {
  codex_owner_api_key_file = "${pathexpand("~/.config/homelab/tailscale/codex-signer-owner-api-key")}"
}

provider "tailscale" {
  alias               = "codex_bootstrap"
  api_key             = fileexists(local.codex_owner_api_key_file) ? "file:$${local.codex_owner_api_key_file}" : null
  oauth_client_id     = fileexists(local.codex_owner_api_key_file) ? null : "file:${pathexpand("~/.config/homelab/tailscale/terragrunt-oauth-client-id")}"
  oauth_client_secret = fileexists(local.codex_owner_api_key_file) ? null : "file:${pathexpand("~/.config/homelab/tailscale/terragrunt-oauth-client-secret")}"
}
EOF
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${read_terragrunt_config(find_in_parent_folders("root.hcl")).locals.aws_region}"
}
EOF
}

inputs = {
  # Generation 2 exists in encrypted state since 2026-10-14 UTC; rotate 60 days after provider creation.
  ci_key_generation = 2
  policy            = file("${dirname(find_in_parent_folders("root.hcl"))}/../scripts/config/tailscale-policy.json")
}
