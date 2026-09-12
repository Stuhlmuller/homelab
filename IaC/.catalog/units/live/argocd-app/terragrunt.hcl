include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
}

terraform {
  source = "../../../modules/argocd-application-kubernetes"

  before_hook "n8n_checkpoint_guard" {
    commands = ["plan", "apply", "destroy", "import", "refresh"]
    execute = [
      "python3", "${get_repo_root()}/scripts/n8n-checkpoint-phase.py", "guard",
      "--manifest-json", jsonencode(local.stack_values.manifest),
      "--command", get_terraform_command(),
      "--arguments-json", jsonencode(get_terraform_cli_args())
    ]
  }
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
