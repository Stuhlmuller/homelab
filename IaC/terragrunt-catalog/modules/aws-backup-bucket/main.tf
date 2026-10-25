terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.63.0"
    }
  }
}

variable "bucket_name" {
  type        = string
  description = "Dedicated bucket name, including the owner account and region suffix."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "Use a 3-63 character lowercase, hyphenated S3 bucket name."
  }
}

variable "expected_account_id" {
  type        = string
  description = "AWS account authorized to own the bucket."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "The expected owner must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  type        = string
  description = "Explicit region for both the bucket and its AWS-managed S3 KMS key."
}

variable "tags" {
  type        = map(string)
  description = "Repository ownership and purpose tags."
}

variable "publisher" {
  type = object({
    role_name     = string
    object_prefix = string
    subject       = string
    workflow      = string
    ref           = string
    repository_id = number
  })
  description = "Optional prefix-scoped GitHub OIDC publisher; null creates no identity."
  default     = null

  validation {
    condition = var.publisher == null || (
      can(regex("^[a-z0-9][a-z0-9-]{1,62}$", var.publisher.role_name)) &&
      can(regex("^[a-z0-9-]+(/[a-z0-9-]+)+/$", var.publisher.object_prefix)) &&
      can(regex("^repo:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:environment:[A-Za-z0-9_.-]+$", var.publisher.subject)) &&
      can(regex("^[A-Za-z][A-Za-z0-9 -]+$", var.publisher.workflow)) &&
      var.publisher.ref == "refs/heads/main" &&
      var.publisher.repository_id > 0
    )
    error_message = "A publisher needs a named role, path prefix, exact environment subject, workflow, main ref and repository ID."
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_iam_openid_connect_provider" "github_actions" {
  count = var.publisher == null ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  bucket_arn = "arn:aws:s3:::${var.bucket_name}"
  kms_alias  = "arn:aws:kms:${var.aws_region}:${var.expected_account_id}:alias/aws/s3"
}

resource "aws_s3_bucket" "backup" {
  # checkov:skip=CKV_AWS_18:Access logging needs a separately owned log destination; none is declared in this change.
  # checkov:skip=CKV_AWS_144:This dedicated offsite copy has no second replication region or destination selected.
  # checkov:skip=CKV2_AWS_62:No event consumer is declared; publication and verification remain a separate operator workflow.
  bucket        = var.bucket_name
  force_destroy = false
  tags          = var.tags

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "The active AWS credentials do not belong to the declared backup owner."
    }

    precondition {
      condition     = data.aws_region.current.region == var.aws_region
      error_message = "The AWS provider region differs from the declared backup region."
    }

    precondition {
      condition     = endswith(var.bucket_name, "-${var.expected_account_id}-${var.aws_region}")
      error_message = "The dedicated bucket name must end with its declared account and region."
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backup" {
  bucket                = aws_s3_bucket.backup.id
  expected_bucket_owner = var.expected_account_id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket                = aws_s3_bucket.backup.id
  expected_bucket_owner = var.expected_account_id
  rule {
    blocked_encryption_types = ["SSE-C"]
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = local.kms_alias
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "backup" {
  bucket = aws_s3_bucket.backup.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.backup]
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket                = aws_s3_bucket.backup.id
  expected_bucket_owner = var.expected_account_id
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
  depends_on = [aws_s3_bucket_versioning.backup]
}

output "bucket_name" {
  value = aws_s3_bucket.backup.id
}

output "bucket_arn" {
  value = aws_s3_bucket.backup.arn
}

output "region" {
  value = var.aws_region
}

# The optional publisher is a separate identity. Its permissions boundary caps
# future attachments as well as this module's inline policy at one object path.
locals {
  publisher_policy = var.publisher == null ? null : jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InspectRecoveryBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
        Resource = local.bucket_arn
      },
      {
        Sid      = "ListRecoveryVersions"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = local.bucket_arn
        Condition = {
          StringLike = { "s3:prefix" = "${var.publisher.object_prefix}*" }
        }
      },
      {
        Sid      = "PublishAndVerifyRecoveryObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${local.bucket_arn}/${var.publisher.object_prefix}*"
      },
      {
        Sid      = "UseOnlyBucketS3Key"
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = "arn:aws:kms:${var.aws_region}:${var.expected_account_id}:key/*"
        Condition = {
          "ForAnyValue:StringEquals" = { "kms:ResourceAliases" = "alias/aws/s3" }
          StringEquals = {
            "kms:ViaService"                   = "s3.${var.aws_region}.amazonaws.com"
            "kms:EncryptionContext:aws:s3:arn" = local.bucket_arn
          }
        }
      },
    ]
  })
}

resource "aws_iam_policy" "publisher_boundary" {
  count       = var.publisher == null ? 0 : 1
  name        = "${var.publisher.role_name}-boundary"
  description = "Limits Enterprise recovery publication to its own versioned S3 prefix."
  policy      = local.publisher_policy
  tags        = var.tags
}

resource "aws_iam_role" "publisher" {
  count = var.publisher == null ? 0 : 1
  name  = var.publisher.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github_actions[0].arn }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"           = var.publisher.subject
          "token.actions.githubusercontent.com:workflow"      = var.publisher.workflow
          "token.actions.githubusercontent.com:ref"           = var.publisher.ref
          "token.actions.githubusercontent.com:repository_id" = tostring(var.publisher.repository_id)
        }
      }
    }]
  })
  permissions_boundary = aws_iam_policy.publisher_boundary[0].arn
  max_session_duration = 3600
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "publisher" {
  count  = var.publisher == null ? 0 : 1
  name   = "prefix-only-recovery-publication"
  role   = aws_iam_role.publisher[0].id
  policy = local.publisher_policy
}

output "publisher_role_arn" {
  value = var.publisher == null ? null : aws_iam_role.publisher[0].arn
}
