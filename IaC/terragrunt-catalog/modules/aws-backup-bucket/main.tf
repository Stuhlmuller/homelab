data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

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
