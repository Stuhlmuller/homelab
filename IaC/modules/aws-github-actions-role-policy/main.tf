data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_kms_alias" "runtime_secret" {
  name = var.kms_key_id
}

data "aws_kms_alias" "state" {
  provider = aws.state
  name     = var.kms_key_id
}

data "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  parameter_reader_group_arn = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:group/${var.parameter_reader_group_name}"
  parameter_reader_policy_arns = [
    for index in range(var.parameter_reader_policy_slot_count) :
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/${var.parameter_reader_policy_name_prefix}${format("%02d", index)}"
  ]
  state_bucket_arn = "arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}"
  state_object_arn = "${local.state_bucket_arn}/${var.state_key_prefix}/*"
}

data "aws_iam_policy_document" "parameter_reader_administration" {
  statement {
    sid    = "CreateTaggedHomelabParameterReaderPolicies"
    effect = "Allow"

    actions = [
      "iam:CreatePolicy",
      "iam:TagPolicy",
    ]

    resources = local.parameter_reader_policy_arns

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = ["homelab"]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["ManualBuild", "ManualTags", "Owner", "Project"]
    }
  }

  statement {
    sid    = "ManageHomelabParameterReaderPolicyLifecycle"
    effect = "Allow"

    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:ListPolicyTags",
      "iam:ListPolicyVersions",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]

    resources = local.parameter_reader_policy_arns
  }

  statement {
    sid    = "AttachHomelabParameterReaderPolicies"
    effect = "Allow"

    actions = [
      "iam:AttachGroupPolicy",
      "iam:DetachGroupPolicy",
    ]

    resources = [local.parameter_reader_group_arn]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = local.parameter_reader_policy_arns
    }
  }

  statement {
    sid       = "ListHomelabParameterReaderPolicyAttachments"
    effect    = "Allow"
    actions   = ["iam:ListAttachedGroupPolicies"]
    resources = [local.parameter_reader_group_arn]
  }
}

data "aws_iam_policy_document" "github_actions_assume_role" {
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
      values = [
        "repo:Stuhlmuller/github-iac:environment:github-iac-plan",
        "repo:Stuhlmuller/github-iac:environment:github-iac-production",
        "repo:Stuhlmuller/homelab:environment:homelab-plan",
        "repo:Stuhlmuller/homelab:environment:homelab-production",
      ]
    }
  }
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
    sid       = "ReadArgoCdApplicationStateObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [local.state_object_arn]
  }

  statement {
    sid       = "ListArgoCdApplicationStatePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.state_key_prefix}/*"]
    }
  }

  statement {
    sid    = "UseStateAndPlanEncryptionKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKey",
    ]
    resources = [data.aws_kms_alias.state.target_key_arn]
  }

  statement {
    sid           = "DenyStateObjectReadsOutsidePrefix"
    effect        = "Deny"
    actions       = ["s3:GetObject"]
    not_resources = [local.state_object_arn]
  }

  statement {
    sid           = "DenyStateBucketListingOutsideBucket"
    effect        = "Deny"
    actions       = ["s3:ListBucket"]
    not_resources = [local.state_bucket_arn]
  }

  statement {
    sid       = "DenyStateBucketListingOutsidePrefix"
    effect    = "Deny"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringNotLike"
      variable = "s3:prefix"
      values   = ["${var.state_key_prefix}/*"]
    }
  }

  statement {
    sid    = "DenyKeyUseOutsideStateKey"
    effect = "Deny"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKey",
    ]
    not_resources = [data.aws_kms_alias.state.target_key_arn]
  }

  statement {
    sid    = "DenyActionsOutsideReadOnlyPlan"
    effect = "Deny"
    not_actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKey",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "external_secrets_boundary" {
  statement {
    sid       = "DenyTemporarySessionCredentials"
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]

    condition {
      test     = "Null"
      variable = "aws:TokenIssueTime"
      values   = ["false"]
    }
  }

  statement {
    sid    = "ReadHomelabParameters"
    effect = "Allow"

    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]

    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/homelab/*",
    ]
  }

  statement {
    sid    = "DecryptHomelabParameters"
    effect = "Allow"

    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]

    resources = [data.aws_kms_alias.runtime_secret.target_key_arn]
  }
}

resource "aws_iam_policy" "parameter_reader_administration" {
  name        = var.policy_name
  description = "Allow the homelab GitHub Actions apply role to manage only the SSM reader policy family and its group attachments."
  policy      = data.aws_iam_policy_document.parameter_reader_administration.json
  tags        = var.tags
}

resource "aws_iam_role" "github_actions" {
  name               = var.apply_role_name
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
  tags               = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "parameter_reader_administration" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.parameter_reader_administration.arn
}

resource "aws_iam_policy" "github_actions_plan" {
  name        = var.plan_policy_name
  description = "Allow homelab pull-request plans to read only Argo CD Application state and use its encryption key."
  policy      = data.aws_iam_policy_document.github_actions_plan.json
  tags        = var.tags
}

resource "aws_iam_role" "github_actions_plan" {
  name                 = var.plan_role_name
  assume_role_policy   = data.aws_iam_policy_document.github_actions_plan_assume_role.json
  permissions_boundary = aws_iam_policy.github_actions_plan.arn
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachments_exclusive" "github_actions_plan" {
  role_name   = aws_iam_role.github_actions_plan.name
  policy_arns = [aws_iam_policy.github_actions_plan.arn]
}

resource "aws_iam_role_policies_exclusive" "github_actions_plan" {
  role_name    = aws_iam_role.github_actions_plan.name
  policy_names = []
}

resource "aws_iam_policy" "external_secrets_boundary" {
  name        = var.external_secrets_boundary_policy_name
  description = "Cap the External Secrets IAM user at homelab SSM reads and runtime-secret KMS decryption."
  policy      = data.aws_iam_policy_document.external_secrets_boundary.json
  tags        = var.tags
}

resource "aws_iam_user" "external_secrets" {
  # checkov:skip=CKV_AWS_273: This existing non-human controller identity has no console login; an operator-owned boundary caps it to exact SSM/KMS reads and exclusive resources remove direct policies.
  name                 = var.external_secrets_user_name
  path                 = "/"
  force_destroy        = false
  permissions_boundary = aws_iam_policy.external_secrets_boundary.arn
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_user_policy_attachments_exclusive" "external_secrets" {
  user_name   = aws_iam_user.external_secrets.name
  policy_arns = []
}

resource "aws_iam_user_policies_exclusive" "external_secrets" {
  user_name    = aws_iam_user.external_secrets.name
  policy_names = []
}
