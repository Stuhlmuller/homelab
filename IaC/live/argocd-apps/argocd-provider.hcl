generate "argocd_provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "argocd" {
  core = true
}
EOF
}
