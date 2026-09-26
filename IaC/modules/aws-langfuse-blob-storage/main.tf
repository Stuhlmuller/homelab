terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.63.0, < 7.0"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  bucket_arn = "arn:aws:s3:::${var.bucket_name}"
  kms_alias  = "arn:aws:kms:${var.aws_region}:${var.expected_account_id}:alias/aws/s3"
}

resource "aws_s3_bucket" "langfuse" {
  # checkov:skip=CKV_AWS_18: No separate access-log destination is declared for this private application bucket.
  # checkov:skip=CKV_AWS_144: A second region has not been selected for this homelab telemetry retention tier.
  # checkov:skip=CKV2_AWS_62: No event consumer is declared for Langfuse raw events.
  bucket        = var.bucket_name
  force_destroy = false
  tags          = var.tags

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "The active AWS credentials do not belong to the declared Langfuse bucket owner."
    }

    precondition {
      condition     = data.aws_region.current.region == var.aws_region
      error_message = "The AWS provider region differs from the declared Langfuse bucket region."
    }

    precondition {
      condition     = endswith(var.bucket_name, "-${var.expected_account_id}-${var.aws_region}")
      error_message = "The Langfuse bucket name must end with its declared account and region."
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "langfuse" {
  bucket                  = aws_s3_bucket.langfuse.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  rule {
    blocked_encryption_types = ["SSE-C"]

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = local.kms_alias
    }

    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id
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

  depends_on = [aws_s3_bucket_public_access_block.langfuse]
}

resource "aws_s3_bucket_lifecycle_configuration" "langfuse" {
  bucket = aws_s3_bucket.langfuse.id

  # ponytail: raw event bodies expire after 30 days; increase retention or add archival export when incident/history needs exceed it.
  rule {
    id     = "expire-raw-events"
    status = "Enabled"
    filter {}

    expiration {
      days = 30
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.langfuse]
}

resource "aws_iam_user" "langfuse" {
  # checkov:skip=CKV_AWS_273: Non-human S3 client with no console login; this Talos cluster has no workload IAM federation configured.
  name = "homelab-langfuse-s3"
  path = "/homelab/"
  tags = var.tags
}

data "aws_iam_policy_document" "langfuse" {
  statement {
    sid = "ListLangfuseBlobBucket"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [local.bucket_arn]
  }

  statement {
    sid = "WriteLangfuseBlobObjects"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${local.bucket_arn}/*"]
  }
}

resource "aws_iam_user_policy" "langfuse" {
  # checkov:skip=CKV_AWS_40: One non-human client receives only the exact dedicated bucket permissions, avoiding a reusable broader group.
  name   = "langfuse-blob-storage"
  user   = aws_iam_user.langfuse.name
  policy = data.aws_iam_policy_document.langfuse.json
}

resource "aws_iam_access_key" "langfuse" {
  user = aws_iam_user.langfuse.name
}

resource "aws_ssm_parameter" "access_key_id" {
  region      = var.aws_region
  name        = "/homelab/langfuse/s3-access-key-id"
  description = "Langfuse S3 blob-storage access key ID."
  type        = "SecureString"
  value       = aws_iam_access_key.langfuse.id
  key_id      = var.parameter_kms_key_id
  tags        = var.tags
}

resource "aws_ssm_parameter" "secret_access_key" {
  region      = var.aws_region
  name        = "/homelab/langfuse/s3-secret-access-key"
  description = "Langfuse S3 blob-storage secret access key."
  type        = "SecureString"
  value       = aws_iam_access_key.langfuse.secret
  key_id      = var.parameter_kms_key_id
  tags        = var.tags
}

output "bucket_name" {
  value = aws_s3_bucket.langfuse.id
}

output "region" {
  value = var.aws_region
}
