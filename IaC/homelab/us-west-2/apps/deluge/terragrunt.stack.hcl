unit "argocd_apps_deluge" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/argocd-app"
  path                    = "argocd"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}

unit "deluge_gluetun_election" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/deluge-gluetun-election"
  path                    = "gluetun-election"
  no_dot_terragrunt_stack = true

  values = {
    enabled = false
  }
}
