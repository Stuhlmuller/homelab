unit "argocd_apps_langfuse" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/argocd-app"
  path                    = "argocd"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}

unit "langfuse_blob_storage" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/langfuse-blob-storage"
  path                    = "blob-storage"
  no_dot_terragrunt_stack = true
}
