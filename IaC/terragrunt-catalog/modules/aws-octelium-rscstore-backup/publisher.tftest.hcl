# Plan-only tests use dummy credentials and override every identity read.
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012" }
}

override_data {
  target = data.aws_region.current
  values = { region = "us-east-1" }
}

variables {
  bucket_name         = "homelab-application-backups-123456789012-us-east-1"
  expected_account_id = "123456789012"
  aws_region          = "us-east-1"
  tags                = { Project = "test" }
}

run "scopes_octelium_rscstore_publisher" {
  command = plan

  assert {
    condition = (
      aws_iam_role.publisher.name == "homelab-octelium-rscstore-backup" &&
      aws_iam_role.publisher.max_session_duration == 3600 &&
      jsondecode(aws_iam_role.publisher.assume_role_policy).Statement == [{
        Effect    = "Allow"
        Action    = "sts:AssumeRoleWithWebIdentity"
        Principal = { Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
        Condition = { StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:Stuhlmuller/homelab:environment:octelium-rscstore-backup"
        } }
      }]
    )
    error_message = "Only the dedicated homelab Octelium environment may assume the publisher."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.publisher.policy) == jsondecode(aws_iam_policy.publisher_boundary.policy) &&
      jsondecode(aws_iam_policy.publisher_boundary.policy).Statement == [
        {
          Sid      = "InspectBackupBucket"
          Effect   = "Allow"
          Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
          Resource = "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1"
        },
        {
          Sid      = "ReadBackupVersions"
          Effect   = "Allow"
          Action   = ["s3:GetObjectVersion"]
          Resource = "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1/applications/octelium-rscstore/*"
        },
        {
          Sid      = "DiscoverBackupMarkerVersion"
          Effect   = "Allow"
          Action   = ["s3:GetObject"]
          Resource = "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1/applications/octelium-rscstore/*/complete.json"
        },
        {
          Sid      = "CreateEncryptedBackupObjects"
          Effect   = "Allow"
          Action   = ["s3:PutObject"]
          Resource = "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1/applications/octelium-rscstore/*"
          Condition = { StringEquals = {
            "s3:if-none-match"                               = "*"
            "s3:x-amz-server-side-encryption"                = "aws:kms"
            "s3:x-amz-server-side-encryption-aws-kms-key-id" = "arn:aws:kms:us-east-1:123456789012:alias/aws/s3"
          } }
        },
        {
          Sid      = "UseOnlyBucketS3Key"
          Effect   = "Allow"
          Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
          Resource = "arn:aws:kms:us-east-1:123456789012:key/*"
          Condition = {
            "ForAnyValue:StringEquals" = { "kms:ResourceAliases" = "alias/aws/s3" }
            StringEquals = {
              "kms:ViaService"                   = "s3.us-east-1.amazonaws.com"
              "kms:EncryptionContext:aws:s3:arn" = "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1"
            }
          }
        },
      ]
    )
    error_message = "The boundary must permit only bucket introspection, version reads, marker discovery and conditional encrypted creation within the Octelium prefix."
  }
}

run "rejects_publisher_for_other_bucket" {
  command = plan
  variables {
    bucket_name = "other-backups-123456789012-us-east-1"
  }
  expect_failures = [aws_iam_policy.publisher_boundary]
}

run "rejects_wrong_active_account" {
  command = plan
  variables {
    bucket_name         = "homelab-application-backups-999999999999-us-east-1"
    expected_account_id = "999999999999"
  }
  expect_failures = [aws_iam_policy.publisher_boundary]
}

run "rejects_wrong_provider_region" {
  command = plan
  variables {
    bucket_name = "homelab-application-backups-123456789012-us-west-2"
    aws_region  = "us-west-2"
  }
  expect_failures = [aws_iam_policy.publisher_boundary]
}

