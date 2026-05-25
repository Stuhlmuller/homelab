data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "kms" {
  # checkov:skip=CKV_AWS_111: KMS key bootstrap policy intentionally grants account-root key administration
  # checkov:skip=CKV_AWS_109: KMS key bootstrap policy must let account-root manage the key policy
  # checkov:skip=CKV_AWS_356: KMS key policies use Resource * because the policy is attached to the key itself
  statement {
    sid = "EnableAccountKeyAdministration"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions = [
      "kms:*",
    ]

    resources = ["*"]
  }
}

resource "aws_kms_key" "this" {
  count = var.create_kms_key ? 1 : 0

  region                  = var.aws_region
  description             = var.kms_key_description
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms.json
  tags                    = var.tags
}

resource "aws_kms_alias" "this" {
  count = var.create_kms_key ? 1 : 0

  region        = var.aws_region
  name          = var.kms_key_id
  target_key_id = aws_kms_key.this[0].key_id
}

locals {
  effective_kms_key_id = var.create_kms_key ? aws_kms_alias.this[0].name : var.kms_key_id
}

resource "aws_ssm_parameter" "this" {
  for_each = var.parameters

  region      = var.aws_region
  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = each.value.initial_value
  key_id      = local.effective_kms_key_id
  tier        = each.value.tier
  tags        = var.tags

  lifecycle {
    create_before_destroy = true

    ignore_changes = [
      value,
    ]
  }
}
