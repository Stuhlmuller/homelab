data "aws_caller_identity" "current" {}

data "aws_kms_key" "existing" {
  count = var.create_kms_key ? 0 : 1

  key_id = var.kms_key_id
}

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
  effective_kms_key_id   = var.create_kms_key ? aws_kms_alias.this[0].name : var.kms_key_id
  effective_kms_key_arn  = var.create_kms_key ? aws_kms_key.this[0].arn : data.aws_kms_key.existing[0].arn
  parameter_reader_names = setunion(toset(keys(var.parameters)), var.additional_parameter_reader_names)
  parameter_reader_policy_chunks = length(var.parameter_reader_iam_user_names) > 0 ? {
    for index, names in chunklist(sort(tolist(local.parameter_reader_names)), 25) :
    format("%02d", index) => names
  } : {}
  external_parameters = {
    for name, parameter in var.parameters :
    name => parameter
    if try(parameter.generated, null) == null
  }
  generated_parameters = {
    for name, parameter in var.parameters :
    name => parameter
    if try(parameter.generated, null) != null
  }
  random_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) == null && try(parameter.generated.kind, "password") == "password"
  }
  ecdsa_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) == null && try(parameter.generated.kind, "password") == "ecdsa_private_key"
  }
  sourced_generated_parameters = {
    for name, parameter in local.generated_parameters :
    name => parameter
    if try(parameter.generated.source_parameter, null) != null
  }
  random_generated_values = {
    for name, parameter in local.random_generated_parameters :
    name => "${try(parameter.generated.prefix, "")}${random_password.generated[name].result}"
  }
  ecdsa_generated_values = {
    for name, parameter in local.ecdsa_generated_parameters :
    name => tls_private_key.generated[name].private_key_pem
  }
  direct_generated_values = merge(
    local.random_generated_values,
    local.ecdsa_generated_values,
  )
  generated_values = merge(
    local.direct_generated_values,
    {
      for name, parameter in local.sourced_generated_parameters :
      name => local.direct_generated_values[parameter.generated.source_parameter]
    }
  )
}

resource "random_password" "generated" {
  for_each = local.random_generated_parameters

  length           = each.value.generated.length
  override_special = each.value.generated.override_special
  special          = each.value.generated.special
}

resource "tls_private_key" "generated" {
  for_each = local.ecdsa_generated_parameters

  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "aws_ssm_parameter" "this" {
  for_each = local.external_parameters

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

resource "aws_ssm_parameter" "generated" {
  for_each = local.generated_parameters

  region      = var.aws_region
  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = local.generated_values[each.key]
  key_id      = local.effective_kms_key_id
  tier        = each.value.tier
  tags        = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

moved {
  from = aws_ssm_parameter.this["/homelab/litellm/master-key"]
  to   = aws_ssm_parameter.generated["/homelab/litellm/master-key"]
}

moved {
  from = aws_ssm_parameter.this["/homelab/media-postgres/app-password"]
  to   = aws_ssm_parameter.generated["/homelab/media-postgres/app-password"]
}

moved {
  from = aws_ssm_parameter.this["/homelab/n8n/encryption-key"]
  to   = aws_ssm_parameter.generated["/homelab/n8n/encryption-key"]
}

moved {
  from = aws_ssm_parameter.this["/homelab/openclaw/app-secret"]
  to   = aws_ssm_parameter.generated["/homelab/openclaw/app-secret"]
}

moved {
  from = aws_ssm_parameter.this["/homelab/openclaw/litellm-token"]
  to   = aws_ssm_parameter.generated["/homelab/openclaw/litellm-token"]
}

data "aws_iam_policy_document" "parameter_reader" {
  for_each = local.parameter_reader_policy_chunks

  statement {
    sid = "ReadManagedSsmParameters"

    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]

    resources = [
      for name in each.value :
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(name, "/")}"
    ]
  }

}

data "aws_iam_policy_document" "parameter_reader_kms" {
  count = length(var.parameter_reader_iam_user_names) > 0 ? 1 : 0

  statement {
    sid = "DecryptManagedSsmParameters"

    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]

    resources = [
      local.effective_kms_key_arn,
    ]
  }
}

resource "aws_iam_group" "parameter_readers" {
  count = length(var.parameter_reader_iam_user_names) > 0 ? 1 : 0

  name = "homelab-ssm-parameter-readers"

  lifecycle {
    precondition {
      condition     = length(local.parameter_reader_policy_chunks) <= 10
      error_message = "The SSM parameter reader group cannot attach more than 10 managed IAM policies. Reduce the parameter set or increase the deterministic chunk size."
    }
  }
}

resource "aws_iam_policy" "parameter_reader" {
  for_each = data.aws_iam_policy_document.parameter_reader

  name        = "homelab-ssm-parameter-reader-${each.key}"
  description = "Read one deterministic chunk of exact homelab SSM parameter ARNs."
  policy      = each.value.json
  tags        = var.tags

  lifecycle {
    precondition {
      condition     = length(each.value.json) <= 6144
      error_message = "An SSM parameter reader managed policy exceeds AWS IAM's 6,144-character policy limit. Reduce the deterministic chunk size."
    }
  }
}

resource "aws_iam_group_policy_attachment" "parameter_reader" {
  for_each = aws_iam_policy.parameter_reader

  group      = aws_iam_group.parameter_readers[0].name
  policy_arn = each.value.arn
}

# Keep the existing inline policy address and shrink it only after every
# managed SSM policy is attached. This avoids a reader-permission gap while
# migrating away from the aggregate group inline-policy size limit.
resource "aws_iam_group_policy" "parameter_reader" {
  count = length(var.parameter_reader_iam_user_names) > 0 ? 1 : 0

  group  = aws_iam_group.parameter_readers[0].name
  name   = "homelab-ssm-parameter-reader"
  policy = data.aws_iam_policy_document.parameter_reader_kms[0].json

  depends_on = [
    aws_iam_group_policy_attachment.parameter_reader,
  ]
}

resource "aws_iam_user_group_membership" "parameter_reader" {
  for_each = var.parameter_reader_iam_user_names

  groups = [
    aws_iam_group.parameter_readers[0].name,
  ]
  user = each.value
}
