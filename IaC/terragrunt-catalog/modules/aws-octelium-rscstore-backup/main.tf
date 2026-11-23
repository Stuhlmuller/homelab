data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  bucket_arn = "arn:aws:s3:::${var.bucket_name}"
  kms_alias  = "arn:aws:kms:${var.aws_region}:${var.expected_account_id}:alias/aws/s3"
  role_name  = "homelab-octelium-rscstore-backup"
  object_arn = "${local.bucket_arn}/applications/octelium-rscstore/*"
  publisher_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InspectBackupBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
        Resource = local.bucket_arn
      },
      {
        Sid      = "ReadBackupVersions"
        Effect   = "Allow"
        Action   = ["s3:GetObjectVersion"]
        Resource = local.object_arn
      },
      {
        Sid      = "DiscoverBackupMarkerVersion"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${local.bucket_arn}/applications/octelium-rscstore/*/complete.json"
      },
      {
        Sid      = "DiscoverPreflightReceiptVersion"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${local.bucket_arn}/applications/octelium-rscstore/preflight/*.json"
      },
      {
        Sid      = "CreateEncryptedBackupObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = local.object_arn
        Condition = {
          StringEquals = {
            "s3:if-none-match"                               = "*"
            "s3:x-amz-server-side-encryption"                = "aws:kms"
            "s3:x-amz-server-side-encryption-aws-kms-key-id" = local.kms_alias
          }
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
      }
    ]
  })
}

resource "aws_iam_policy" "publisher_boundary" {
  name        = "${local.role_name}-boundary"
  description = "Limits Octelium resource-store backup publication to its versioned S3 prefix."
  policy      = local.publisher_policy
  tags        = var.tags

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "The AWS credentials must belong to the declared backup account."
    }

    precondition {
      condition     = data.aws_region.current.region == var.aws_region
      error_message = "The AWS provider must use the declared backup region."
    }

    precondition {
      condition     = var.bucket_name == "homelab-application-backups-${var.expected_account_id}-${var.aws_region}"
      error_message = "The Octelium publisher belongs to the declared application backup bucket."
    }
  }
}

resource "aws_iam_role" "publisher" {
  name = local.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = "arn:aws:iam::${var.expected_account_id}:oidc-provider/token.actions.githubusercontent.com" }
      # GitHub environment branch protection controls which refs can obtain
      # this subject. AWS IAM does not expose GitHub workflow or ref claims.
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:Stuhlmuller/homelab:environment:octelium-rscstore-backup"
        }
      }
    }]
  })
  permissions_boundary = aws_iam_policy.publisher_boundary.arn
  max_session_duration = 3600
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "publisher" {
  name   = "prefix-only-backup-publication"
  role   = aws_iam_role.publisher.id
  policy = local.publisher_policy
}

output "publisher_role_arn" {
  value = aws_iam_role.publisher.arn
}
