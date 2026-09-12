terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.63.0, < 7.0"
    }
  }
}

variable "bucket_name" {
  description = "Existing bucket whose encryption configuration this unit owns."
  type        = string
}

variable "default_kms_key_id" {
  description = "Existing default KMS key ARN; explicit per-object keys remain supported."
  type        = string
}

variable "bucket_key_enabled" {
  description = "Cache S3 bucket keys to reduce KMS requests for new object versions."
  type        = bool
}

# Adopt only encryption configuration, never the bucket or its objects.
import {
  to = aws_s3_bucket_server_side_encryption_configuration.this
  id = var.bucket_name
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = var.bucket_name

  rule {
    # Preserve the existing restriction against customer-provided object keys.
    blocked_encryption_types = ["SSE-C"]

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.default_kms_key_id
    }
    bucket_key_enabled = var.bucket_key_enabled
  }

  lifecycle {
    prevent_destroy = true
  }
}
