terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.63.0"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  role_name  = "homelab-platform-etcd-reader"
  bucket_arn = "arn:aws:s3:::${var.bucket_name}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InspectVersionedEtcdBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
        Resource = local.bucket_arn
      },
      {
        Sid      = "ListEtcdObjectVersions"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = local.bucket_arn
        Condition = {
          StringLike = { "s3:prefix" = "etcd/*" }
        }
      },
      {
        Sid      = "ReadVersionedEtcdSnapshotAndManifest"
        Effect   = "Allow"
        Action   = ["s3:GetObjectVersion"]
        Resource = "${local.bucket_arn}/etcd/*"
      },
      {
        Sid      = "ReadBucketS3Checksums"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
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

resource "aws_iam_policy" "boundary" {
  name        = "${local.role_name}-boundary"
  description = "Caps protected platform maintenance at versioned etcd backup reads."
  policy      = local.policy
  tags        = var.tags
}

resource "aws_iam_role" "reader" {
  name = local.role_name
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
          "token.actions.githubusercontent.com:sub"           = "repo:Stuhlmuller/homelab:environment:homelab-production"
          "token.actions.githubusercontent.com:workflow"      = "Platform Maintenance"
          "token.actions.githubusercontent.com:ref"           = "refs/heads/main"
          "token.actions.githubusercontent.com:repository_id" = "973476220"
          "token.actions.githubusercontent.com:actor_id"      = "57728706"
        }
      }
    }]
  })
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 9000
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true

    precondition {
      condition = (
        data.aws_caller_identity.current.account_id == var.expected_account_id &&
        data.aws_region.current.region == var.aws_region &&
        var.aws_region == "us-east-1" &&
        var.bucket_name == "homelab-etcd-backups-${var.expected_account_id}-${var.aws_region}"
      )
      error_message = "The platform etcd reader requires the declared owner, region, and dedicated bucket."
    }
  }
}

resource "aws_iam_role_policy" "reader" {
  name   = "versioned-etcd-read-only"
  role   = aws_iam_role.reader.id
  policy = local.policy
}

output "role_arn" {
  value = aws_iam_role.reader.arn
}
