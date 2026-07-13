data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_kms_alias" "runtime_secret" {
  name = var.kms_key_id
}

locals {
  parameter_reader_group_arn = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:group/${var.parameter_reader_group_name}"
  parameter_reader_policy_arns = [
    for index in range(var.parameter_reader_policy_slot_count) :
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/${var.parameter_reader_policy_name_prefix}${format("%02d", index)}"
  ]
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

data "aws_iam_policy_document" "external_secrets_boundary" {
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

resource "aws_iam_role_policy_attachment" "parameter_reader_administration" {
  role       = var.apply_role_name
  policy_arn = aws_iam_policy.parameter_reader_administration.arn
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
