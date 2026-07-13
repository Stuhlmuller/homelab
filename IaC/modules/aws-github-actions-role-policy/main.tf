data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

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
