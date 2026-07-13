locals {
  root_config            = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  kubernetes_config_path = local.root_config.locals.kubernetes_config_path
}

generate "kubernetes_provider" {
  path      = "kubernetes-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "kubernetes" {
  config_path = pathexpand("${local.kubernetes_config_path}")
}
EOF
}
