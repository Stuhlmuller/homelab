include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/tailscale-access"
}

generate "tailscale_provider" {
  path      = "tailscale-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "tailscale" {
  api_key = "file:${pathexpand("~/.config/homelab/tailscale/api-key")}"
}
EOF
}

inputs = {
  # Generation 1 prepared 2026-10-10 UTC; rotate 60 days after provider creation.
  ci_key_generation = 1
  policy            = file("${dirname(find_in_parent_folders("root.hcl"))}/../scripts/config/tailscale-policy.json")
}
