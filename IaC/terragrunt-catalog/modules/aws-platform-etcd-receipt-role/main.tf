terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.63.0"
    }
  }
}

variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "The bucket owner must be a 12-digit AWS account ID."
  }
}

variable "region" {
  type = string
  validation {
    condition     = var.region == "us-east-1"
    error_message = "The reviewed off-node receipt location is us-east-1."
  }
}

variable "etcd_bucket" {
  type = string
}

variable "receipt_bucket" {
  type = string
}

variable "tags" {
  type = map(string)
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  role_name        = "homelab-platform-etcd-receipt-publisher"
  etcd_arn         = "arn:aws:s3:::${var.etcd_bucket}"
  receipt_arn      = "arn:aws:s3:::${var.receipt_bucket}"
  etcd_prefix      = "etcd/*"
  receipt_prefix   = "openclaw-enterprise/platform/receipts/*/off-node-etcd-backup/*"
  kms_resource_arn = "arn:aws:kms:${var.region}:${var.account_id}:key/*"
  role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CheckVersionedKmsBuckets"
        Effect   = "Allow"
        Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
        Resource = [local.etcd_arn, local.receipt_arn]
      },
      {
        Sid      = "ListOnlyEtcdSnapshotVersions"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = local.etcd_arn
        Condition = {
          StringLike = { "s3:prefix" = local.etcd_prefix }
        }
      },
      {
        Sid      = "ReadOnlyEtcdSnapshotVersions"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${local.etcd_arn}/${local.etcd_prefix}"
      },
      {
        Sid      = "ListOnlyEtcdPrerequisiteVersions"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = local.receipt_arn
        Condition = {
          StringLike = { "s3:prefix" = local.receipt_prefix }
        }
      },
      {
        Sid      = "ReadOnlyEtcdPrerequisiteVersions"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${local.receipt_arn}/${local.receipt_prefix}"
      },
      {
        Sid      = "PublishOnlyEtcdPrerequisite"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${local.receipt_arn}/${local.receipt_prefix}"
        Condition = {
          StringEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" }
        }
      },
      {
        Sid    = "ReadEtcdChecksumThroughS3"
        Effect = "Allow"
        # Checksum-mode HEAD on an SSE-KMS object can require both actions.
        # S3 PutObject remains denied on the source bucket.
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = local.kms_resource_arn
        Condition = {
          "ForAnyValue:StringEquals" = { "kms:ResourceAliases" = "alias/aws/s3" }
          StringEquals = {
            "kms:ViaService"                   = "s3.${var.region}.amazonaws.com"
            "kms:EncryptionContext:aws:s3:arn" = local.etcd_arn
          }
        }
      },
      {
        Sid      = "UseReceiptBucketKeyThroughS3"
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = local.kms_resource_arn
        Condition = {
          "ForAnyValue:StringEquals" = { "kms:ResourceAliases" = "alias/aws/s3" }
          StringEquals = {
            "kms:ViaService"                   = "s3.${var.region}.amazonaws.com"
            "kms:EncryptionContext:aws:s3:arn" = local.receipt_arn
          }
        }
      },
    ]
  })
}

resource "aws_iam_policy" "boundary" {
  name        = "${local.role_name}-boundary"
  description = "Caps the reviewed OIDC job at etcd snapshot reads and one receipt prefix."
  policy      = local.role_policy
  tags        = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "publisher" {
  name = local.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRoleWithWebIdentity"
      Principal = {
        Federated = "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"           = "repo:Stuhlmuller/homelab:environment:homelab-production"
          "token.actions.githubusercontent.com:workflow"      = "Platform Etcd Prerequisite Publication"
          "token.actions.githubusercontent.com:ref"           = "refs/heads/main"
          "token.actions.githubusercontent.com:repository_id" = "973476220"
          "token.actions.githubusercontent.com:actor_id"      = "57728706"
        }
      }
    }]
  })
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 3600
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (data.aws_caller_identity.current.account_id == var.account_id &&
        data.aws_region.current.region == var.region &&
        var.etcd_bucket == "homelab-etcd-backups-${var.account_id}-${var.region}" &&
      var.receipt_bucket == "homelab-application-backups-${var.account_id}-${var.region}")
      error_message = "The reviewed role requires the exact owner, region, and bucket pair."
    }
  }
}

resource "aws_iam_role_policy" "publisher" {
  name   = "read-etcd-publish-exact-prerequisite"
  role   = aws_iam_role.publisher.id
  policy = local.role_policy
}

output "role_arn" {
  value = aws_iam_role.publisher.arn
}
