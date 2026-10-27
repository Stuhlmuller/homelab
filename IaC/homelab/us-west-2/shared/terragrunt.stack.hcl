unit "aws_ssm_parameters" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/aws-ssm-parameters"
  path                    = "aws-ssm-parameters"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_node_labels" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/kubernetes-node-labels"
  path                    = "kubernetes-node-labels"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_secrets_external_secrets_aws_ssm_auth" {
  source                  = "${dirname(find_in_parent_folders("root.hcl"))}/terragrunt-catalog/units/live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  path                    = "kubernetes-secrets/external-secrets-aws-ssm-auth"
  no_dot_terragrunt_stack = true
}
