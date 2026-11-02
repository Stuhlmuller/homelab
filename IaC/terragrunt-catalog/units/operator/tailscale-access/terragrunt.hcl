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

# Owner API credentials are used only for Codex enrollment resources. The
# existing OAuth client cannot create OAuth clients or manage this webhook.
provider "tailscale" {
  alias   = "codex_bootstrap"
  api_key = "file:${pathexpand("~/.config/homelab/tailscale/codex-signer-owner-api-key")}"
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
