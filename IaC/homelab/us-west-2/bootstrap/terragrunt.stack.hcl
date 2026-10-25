unit "bootstrap_argocd" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/bootstrap/argocd"
  path                    = "argocd"
  no_dot_terragrunt_stack = true
}
