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

variable "platform_receipt_publisher" {
  type = object({
    role_name     = string
    source_bucket = string
    subject       = string
    workflow      = string
    ref           = string
    repository_id = number
  })
  description = "Optional protected platform prerequisite publisher and read-only etcd evidence source."
  default     = null

  validation {
    condition = var.platform_receipt_publisher == null || (
      var.platform_receipt_publisher.role_name == "homelab-platform-receipt-publisher" &&
      var.platform_receipt_publisher.source_bucket == "homelab-etcd-backups-${var.expected_account_id}-${var.aws_region}" &&
      var.platform_receipt_publisher.subject == "repo:Stuhlmuller/homelab:environment:homelab-production" &&
      var.platform_receipt_publisher.workflow == "Platform Recovery Receipt Publication" &&
      var.platform_receipt_publisher.ref == "refs/heads/main" &&
      var.platform_receipt_publisher.repository_id == 973476220
    )
    error_message = "Platform receipt publication is pinned to its reviewed repository, workflow, environment, identity and etcd source bucket."
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  bucket_arn          = "arn:aws:s3:::${var.bucket_name}"
  kms_alias           = "arn:aws:kms:${var.aws_region}:${var.expected_account_id}:alias/aws/s3"
  platform_source_arn = var.platform_receipt_publisher == null ? null : "arn:aws:s3:::${var.platform_receipt_publisher.source_bucket}"
  platform_role_arn   = var.platform_receipt_publisher == null ? null : "arn:aws:iam::${var.expected_account_id}:role/${var.platform_receipt_publisher.role_name}"
  prerequisite_keys = [for name in ["placement", "direct-recovery", "off-node-etcd-backup", "artifact-publication"] :
  "${local.bucket_arn}/openclaw-enterprise/platform/receipts/*/${name}.json"]
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
    Statement = concat([{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }], [for statement in [{
        Sid       = "DenyOtherPrerequisiteWriters"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:PutObject"]
        Resource  = local.prerequisite_keys
        Condition = {
          ArnNotEquals = { "aws:PrincipalArn" = local.platform_role_arn }
        }
        }, {
        Sid       = "DenyPrerequisiteDeletion"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource  = local.prerequisite_keys
    }] : statement if var.platform_receipt_publisher != null])
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
        Sid      = "ReadRecoveryObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${local.bucket_arn}/${var.publisher.object_prefix}*"
      },
      {
        Sid      = "PublishKmsRecoveryObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${local.bucket_arn}/${var.publisher.object_prefix}*"
        # An absent header uses the bucket's SSE-KMS default; a caller may not
        # override it with SSE-S3. Multipart part requests omit this header.
        Condition = {
          StringEqualsIfExists = { "s3:x-amz-server-side-encryption" = "aws:kms" }
        }
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
      Effect = "Allow"
      Action = "sts:AssumeRoleWithWebIdentity"
      # The CI plan role cannot enumerate IAM providers; the owner account is checked above.
      Principal = { Federated = "arn:aws:iam::${var.expected_account_id}:oidc-provider/token.actions.githubusercontent.com" }
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

# A distinct OIDC role reads non-authoritative operator candidates and immutable
# etcd versions, then writes only the four fixed prerequisite receipt names.
# The bucket policy prevents the shared CI role or administrator sessions from
# forging those authoritative keys without changing reviewed infrastructure.
locals {
  platform_receipt_policy = var.platform_receipt_publisher == null ? null : jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InspectEvidenceAndReceiptBuckets"
        Effect   = "Allow"
        Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
        Resource = [local.bucket_arn, local.platform_source_arn]
      },
      {
        Sid      = "InspectAuthoritativeBucketGuard"
        Effect   = "Allow"
        Action   = ["s3:GetBucketPolicy"]
        Resource = local.bucket_arn
      },
      {
        Sid      = "ListStagedCandidateAndEtcdVersions"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = local.platform_source_arn
        Condition = {
          StringLike = { "s3:prefix" = ["platform-candidates/*", "etcd/*"] }
        }
      },
      {
        Sid      = "ReadStagedCandidateAndEtcdVersions"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${local.platform_source_arn}/platform-candidates/*", "${local.platform_source_arn}/etcd/*"]
      },
      {
        Sid      = "ListPublishedPrerequisiteVersions"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = local.bucket_arn
        Condition = {
          StringLike = { "s3:prefix" = "openclaw-enterprise/platform/receipts/*" }
        }
      },
      {
        Sid      = "ReadPublishedPrerequisites"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = local.prerequisite_keys
      },
      {
        Sid      = "PublishKmsPrerequisites"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = local.prerequisite_keys
        Condition = {
          StringEqualsIfExists = { "s3:x-amz-server-side-encryption" = "aws:kms" }
        }
      },
      {
        Sid      = "UseOnlyTheBucketsS3KmsKey"
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = "arn:aws:kms:${var.aws_region}:${var.expected_account_id}:key/*"
        Condition = {
          "ForAnyValue:StringEquals" = { "kms:ResourceAliases" = "alias/aws/s3" }
          StringEquals = {
            "kms:ViaService"                   = "s3.${var.aws_region}.amazonaws.com"
            "kms:EncryptionContext:aws:s3:arn" = [local.bucket_arn, local.platform_source_arn]
          }
        }
      },
    ]
  })
}

resource "aws_iam_policy" "platform_receipt_boundary" {
  count       = var.platform_receipt_publisher == null ? 0 : 1
  name        = "${var.platform_receipt_publisher.role_name}-boundary"
  description = "Caps platform receipt publication and immutable etcd evidence reads."
  policy      = local.platform_receipt_policy
  tags        = var.tags
}

resource "aws_iam_role" "platform_receipt_publisher" {
  count = var.platform_receipt_publisher == null ? 0 : 1
  name  = var.platform_receipt_publisher.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRoleWithWebIdentity"
      Principal = {
        Federated = "arn:aws:iam::${var.expected_account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"           = var.platform_receipt_publisher.subject
          "token.actions.githubusercontent.com:workflow"      = var.platform_receipt_publisher.workflow
          "token.actions.githubusercontent.com:ref"           = var.platform_receipt_publisher.ref
          "token.actions.githubusercontent.com:repository_id" = tostring(var.platform_receipt_publisher.repository_id)
          "token.actions.githubusercontent.com:actor_id"      = "57728706"
        }
      }
    }]
  })
  permissions_boundary = aws_iam_policy.platform_receipt_boundary[0].arn
  max_session_duration = 3600
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "platform_receipt_publisher" {
  count  = var.platform_receipt_publisher == null ? 0 : 1
  name   = "platform-prerequisites-only"
  role   = aws_iam_role.platform_receipt_publisher[0].id
  policy = local.platform_receipt_policy
}

output "platform_receipt_publisher_role_arn" {
  value = var.platform_receipt_publisher == null ? null : aws_iam_role.platform_receipt_publisher[0].arn
}
