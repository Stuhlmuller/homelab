include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"
}

locals {
  stack_values = jsondecode(read_tfvars_file("terragrunt.values.hcl"))
}

dependencies {
  paths = [
    for dependency in local.stack_values.dependencies :
    "${get_terragrunt_dir()}/../${dependency}"
  ]
}

inputs = {
  manifest = local.stack_values.manifest
}
