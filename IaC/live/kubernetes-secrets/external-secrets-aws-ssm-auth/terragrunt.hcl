include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/kubernetes-secret-from-ssm"
}

dependencies {
  paths = [
    "../../aws-ssm-parameters",
    "../../argocd-apps/external-secrets",
  ]
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "us-east-1"
}
EOF
}

inputs = {
  name      = "aws-ssm-auth"
  namespace = "external-secrets"

  labels = {
    "app.kubernetes.io/managed-by" = "terragrunt"
    "app.kubernetes.io/name"       = "aws-ssm-auth"
    "app.kubernetes.io/part-of"    = "external-secrets"
  }

  annotations = {
    "homelab.rst.io/secret-source" = "aws-ssm-parameter-store"
  }

  data_ssm_parameter_names = {
    "access-key-id"     = "/homelab/external-secrets/aws-ssm/access-key-id"
    "secret-access-key" = "/homelab/external-secrets/aws-ssm/secret-access-key"
  }
}
