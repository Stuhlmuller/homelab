include "root" {
  path = find_in_parent_folders("root.hcl")
}
locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  values      = jsondecode(read_tfvars_file("terragrunt.values.hcl"))
}
terraform {
  source = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/modules/azuread-oidc-application"
}
dependencies {
  paths = ["${dirname(find_in_parent_folders("root.hcl"))}/homelab/us-west-2/shared/aws-ssm-parameters"]
}
inputs = merge(local.values, {
  aws_region           = local.root_config.locals.aws_region
  parameter_kms_key_id = local.root_config.locals.runtime_kms_key_id
  parameter_tags       = { for key, value in local.root_config.locals.default_tags : key => tostring(value) }
})
