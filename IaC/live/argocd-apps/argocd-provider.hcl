generate "argocd_provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "argocd" {
  server_addr = "localhost:18080"
  plain_text  = true
}
EOF
}
