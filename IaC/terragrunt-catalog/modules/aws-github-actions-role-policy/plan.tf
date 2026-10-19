data "aws_kms_alias" "state" {
  provider = aws.state
  name     = var.state_kms_key_id
}

locals {
  # Only the generated Grafana and Octelium AzureAD registration units read
  # SSM during PR planning. Keep their exact names in sync with those units.
  plan_sso_parameter_arns = [
    for name in [
      "homelab/grafana/azuread/allowed-organizations",
      "homelab/grafana/azuread/auth-url",
      "homelab/grafana/azuread/client-id",
      "homelab/grafana/azuread/client-secret",
      "homelab/grafana/azuread/token-url",
      "homelab/octelium/entra/client-id",
      "homelab/octelium/entra/client-secret",
      "homelab/octelium/entra/issuer-url",
      "homelab/octelium/entra/tenant-id",
    ] : "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${name}"
  ]
}

data "aws_iam_policy_document" "github_actions_plan_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      identifiers = [data.aws_iam_openid_connect_provider.github_actions.arn]
      type        = "Federated"
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:Stuhlmuller/homelab:environment:homelab-plan"]
    }
  }
}

data "aws_iam_policy_document" "github_actions_plan" {
  statement {
    sid       = "ReadHomelabStateBucket"
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}"]
  }

  statement {
    sid       = "ReadHomelabStateObjects"
    actions   = ["s3:GetObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}/IaC/homelab/*"]
  }

  statement {
    sid       = "InspectApplicationBackupBucket"
    actions   = ["s3:Get*", "s3:List*"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.backup_bucket_name}"]
  }

  statement {
    sid       = "ReadAzureadSsoParameters"
    actions   = ["ssm:GetParameter", "ssm:ListTagsForResource"]
    resources = local.plan_sso_parameter_arns
  }

  # The AWS provider calls DescribeParameters for each managed parameter.
  # This API cannot be restricted to parameter ARNs and returns metadata only.
  statement {
    sid       = "DescribeAzureadSsoParameters"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
  }

  statement {
    sid       = "DecryptAzureadSsoParameters"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.runtime_secret.target_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values   = local.plan_sso_parameter_arns
    }
  }

  statement {
    sid       = "ReadEncryptedStateAndWriteLocalPlans"
    actions   = ["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey"]
    resources = [data.aws_kms_alias.state.target_key_arn]
  }
}

resource "aws_iam_role" "github_actions_plan" {
  name               = var.plan_role_name
  assume_role_policy = data.aws_iam_policy_document.github_actions_plan_assume_role.json
  tags               = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "github_actions_plan" {
  name   = "read-homelab-plan-inputs"
  role   = aws_iam_role.github_actions_plan.id
  policy = data.aws_iam_policy_document.github_actions_plan.json
}
