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
      data.aws_kms_key.existing.arn,
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

# Parameter reads use chunked managed policies; the inline policy grants KMS
# access only after every reader policy is attached.
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
