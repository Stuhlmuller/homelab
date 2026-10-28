data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_kms_alias" "runtime_secret" {
  name = var.kms_key_id
}

data "aws_kms_alias" "langfuse_s3" {
  name = "alias/aws/s3"
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
  langfuse_blob_storage_user_arn = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:user/homelab/homelab-langfuse-s3"
  langfuse_bucket_arn            = "arn:${data.aws_partition.current.partition}:s3:::${var.langfuse_bucket_name}"
  application_backup_bucket_arn  = "arn:${data.aws_partition.current.partition}:s3:::${var.application_backup_bucket_name}"
}

data "aws_iam_policy_document" "langfuse_raw_inventory" {
  statement {
    sid    = "InspectLangfuseRawBucket"
    effect = "Allow"
    actions = [
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:ListBucketVersions",
    ]
    resources = [local.langfuse_bucket_arn]
  }

  statement {
    sid       = "ReadLangfuseRawVersions"
    effect    = "Allow"
    actions   = ["s3:GetObjectVersion"]
    resources = ["${local.langfuse_bucket_arn}/*"]
  }

  statement {
    sid       = "DecryptLangfuseRawVersions"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.langfuse_s3.target_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    # S3 Bucket Keys use the bucket ARN as their KMS encryption context.
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = [local.langfuse_bucket_arn]
    }
  }
}

# This second role can copy exact source versions into one offsite prefix. The
# read-only inventory role remains unchanged and cannot publish backup data.
data "aws_iam_policy_document" "langfuse_raw_backup" {
  statement {
    sid       = "InspectRawAndBackupBuckets"
    effect    = "Allow"
    actions   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
    resources = [local.langfuse_bucket_arn, local.application_backup_bucket_arn]
  }

  statement {
    sid       = "ListLangfuseRawVersions"
    effect    = "Allow"
    actions   = ["s3:ListBucketVersions"]
    resources = [local.langfuse_bucket_arn]
  }

  statement {
    sid       = "ReadLangfuseRawVersions"
    effect    = "Allow"
    actions   = ["s3:GetObjectVersion", "s3:GetObjectVersionTagging"]
    resources = ["${local.langfuse_bucket_arn}/*"]
  }

  statement {
    sid    = "WriteAndReadLangfuseBackupVersions"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:PutObjectTagging",
      "s3:GetObjectVersion",
      "s3:GetObjectVersionTagging",
    ]
    resources = ["${local.application_backup_bucket_arn}/langfuse/raw-versions/*"]

    condition {
      test     = "StringEqualsIfExists"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid       = "DecryptLangfuseRawVersions"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.langfuse_s3.target_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = [local.langfuse_bucket_arn]
    }
  }

  statement {
    sid       = "EncryptAndDecryptLangfuseBackupVersions"
    effect    = "Allow"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = ["arn:${data.aws_partition.current.partition}:kms:us-east-1:${data.aws_caller_identity.current.account_id}:key/*"]

    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "kms:ResourceAliases"
      values   = ["alias/aws/s3"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.us-east-1.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = [local.application_backup_bucket_arn]
    }
  }
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

  statement {
    sid       = "DescribeRuntimeSecretKey"
    effect    = "Allow"
    actions   = ["kms:DescribeKey"]
    resources = [data.aws_kms_alias.runtime_secret.target_key_arn]
  }

  statement {
    sid    = "ReadLangfuseBlobStorageIdentity"
    effect = "Allow"
    actions = [
      "iam:GetUser",
      "iam:ListAccessKeys",
      "iam:GetUserPolicy",
    ]
    resources = [local.langfuse_blob_storage_user_arn]
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

data "aws_iam_policy_document" "langfuse_raw_inventory_assume_role" {
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
      values   = ["repo:Stuhlmuller/homelab:environment:homelab-production"]
    }
  }
}

data "aws_iam_policy_document" "langfuse_raw_backup_assume_role" {
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
      values   = ["repo:Stuhlmuller/homelab:environment:homelab-production"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:workflow"
      values   = ["Langfuse Raw Version Backup"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:ref"
      values   = ["refs/heads/main"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_id"
      values   = ["973476220"]
    }
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

    # SSM forwards the caller's identity to KMS to decrypt SecureStrings.
    # Deny direct STS requests without denying that AWS-managed service hop.
    condition {
      test     = "Bool"
      variable = "aws:ViaAWSService"
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
  name                 = var.apply_role_name
  assume_role_policy   = data.aws_iam_policy_document.github_actions_assume_role.json
  max_session_duration = 25200 # Seven hours: the protected legacy archive job can run for six hours.
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "parameter_reader_administration" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.parameter_reader_administration.arn
}

resource "aws_iam_role" "langfuse_raw_inventory" {
  name                 = "homelab-langfuse-raw-inventory"
  assume_role_policy   = data.aws_iam_policy_document.langfuse_raw_inventory_assume_role.json
  max_session_duration = 7200
  tags                 = var.tags
}

resource "aws_iam_role_policy" "langfuse_raw_inventory" {
  name   = "langfuse-raw-version-inventory"
  role   = aws_iam_role.langfuse_raw_inventory.name
  policy = data.aws_iam_policy_document.langfuse_raw_inventory.json

  lifecycle {
    precondition {
      condition     = var.langfuse_bucket_name == "homelab-langfuse-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
      error_message = "The raw-version inventory grant must match the declared Langfuse bucket owner and region."
    }
  }
}

resource "aws_iam_policy" "langfuse_raw_backup_boundary" {
  name        = "homelab-langfuse-raw-backup-boundary"
  description = "Caps raw-version backup access to the two declared buckets and their S3 KMS keys."
  policy      = data.aws_iam_policy_document.langfuse_raw_backup.json
  tags        = var.tags
}

resource "aws_iam_role" "langfuse_raw_backup" {
  name                 = "homelab-langfuse-raw-backup"
  assume_role_policy   = data.aws_iam_policy_document.langfuse_raw_backup_assume_role.json
  permissions_boundary = aws_iam_policy.langfuse_raw_backup_boundary.arn
  max_session_duration = 21600
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "langfuse_raw_backup" {
  name   = "langfuse-raw-version-backup"
  role   = aws_iam_role.langfuse_raw_backup.name
  policy = data.aws_iam_policy_document.langfuse_raw_backup.json

  lifecycle {
    precondition {
      condition = (
        var.langfuse_bucket_name == "homelab-langfuse-${data.aws_caller_identity.current.account_id}-${var.aws_region}" &&
        var.application_backup_bucket_name == "homelab-application-backups-${data.aws_caller_identity.current.account_id}-us-east-1"
      )
      error_message = "The raw-version backup role must match both declared bucket owners and regions."
    }
  }
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
