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
  bucket_name         = "test-etcd-backups-123456789012-us-east-1"
  expected_account_id = "123456789012"
  aws_region          = "us-east-1"
  tags                = { Project = "test" }
}

run "retains_completed_backups" {
  command = plan

  assert {
    condition = (
      length(aws_iam_policy.publisher_boundary) == 0 &&
      length(aws_iam_role.publisher) == 0 &&
      length(aws_iam_role_policy.publisher) == 0
    )
    error_message = "The shared bucket module must create no publisher without an explicit input."
  }

  assert {
    condition = (
      !aws_s3_bucket.backup.force_destroy &&
      aws_s3_bucket_versioning.backup.versioning_configuration[0].status == "Enabled" &&
      length(aws_s3_bucket_lifecycle_configuration.backup.rule) == 1 &&
      alltrue([for rule in aws_s3_bucket_lifecycle_configuration.backup.rule :
        length(rule.expiration) == 0 &&
        length(rule.noncurrent_version_expiration) == 0 &&
        length(rule.transition) == 0 &&
        length(rule.noncurrent_version_transition) == 0 &&
        rule.abort_incomplete_multipart_upload[0].days_after_initiation == 7
      ])
    )
    error_message = "Completed backup versions must survive; only incomplete multipart uploads may expire."
  }

  assert {
    condition = (
      aws_s3_bucket_ownership_controls.backup.rule[0].object_ownership == "BucketOwnerEnforced" &&
      aws_s3_bucket_public_access_block.backup.block_public_acls &&
      aws_s3_bucket_public_access_block.backup.block_public_policy &&
      aws_s3_bucket_public_access_block.backup.ignore_public_acls &&
      aws_s3_bucket_public_access_block.backup.restrict_public_buckets &&
      alltrue([for rule in aws_s3_bucket_server_side_encryption_configuration.backup.rule :
        rule.apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms" &&
        rule.apply_server_side_encryption_by_default[0].kms_master_key_id == "arn:aws:kms:us-east-1:123456789012:alias/aws/s3" &&
        rule.bucket_key_enabled
      ])
    )
    error_message = "The bucket must remain private, owner-enforced, and encrypted with the declared account's regional S3 key."
  }

  assert {
    condition = jsondecode(aws_s3_bucket_policy.backup.policy) == {
      Version = "2012-10-17"
      Statement = [{
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = ["arn:aws:s3:::test-etcd-backups-123456789012-us-east-1", "arn:aws:s3:::test-etcd-backups-123456789012-us-east-1/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }]
    }
    error_message = "The transport policy must cover this bucket and its objects and grant no new access."
  }
}

run "scopes_optional_enterprise_publisher" {
  command = plan
  variables {
    publisher = {
      role_name     = "homelab-oce-recovery-publisher"
      object_prefix = "openclaw-enterprise/new/"
      subject       = "repo:Stuhlmuller/homelab:environment:homelab-production"
      workflow      = "OpenClaw Enterprise Recovery Publication"
      ref           = "refs/heads/main"
      repository_id = 973476220
    }
  }

  assert {
    condition = (
      length(aws_iam_role.publisher) == 1 &&
      aws_iam_role.publisher[0].name == "homelab-oce-recovery-publisher" &&
      aws_iam_role.publisher[0].max_session_duration == 3600 &&
      jsondecode(aws_iam_role.publisher[0].assume_role_policy).Statement == [{
        Effect    = "Allow"
        Action    = "sts:AssumeRoleWithWebIdentity"
        Principal = { Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
        Condition = { StringEquals = {
          "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"           = "repo:Stuhlmuller/homelab:environment:homelab-production"
          "token.actions.githubusercontent.com:workflow"      = "OpenClaw Enterprise Recovery Publication"
          "token.actions.githubusercontent.com:ref"           = "refs/heads/main"
          "token.actions.githubusercontent.com:repository_id" = "973476220"
        } }
      }]
    )
    error_message = "Only the reserved protected main workflow may assume the separate publisher."
  }

  assert {
    condition = (
      length(aws_iam_policy.publisher_boundary) == 1 &&
      length(aws_iam_role_policy.publisher) == 1 &&
      jsondecode(aws_iam_role_policy.publisher[0].policy) == jsondecode(aws_iam_policy.publisher_boundary[0].policy) &&
      jsondecode(aws_iam_policy.publisher_boundary[0].policy).Statement == [
        {
          Sid      = "InspectRecoveryBucket"
          Effect   = "Allow"
          Action   = ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"]
          Resource = "arn:aws:s3:::test-etcd-backups-123456789012-us-east-1"
        },
        {
          Sid      = "ListRecoveryVersions"
          Effect   = "Allow"
          Action   = ["s3:ListBucketVersions"]
          Resource = "arn:aws:s3:::test-etcd-backups-123456789012-us-east-1"
          Condition = { StringLike = {
            "s3:prefix" = "openclaw-enterprise/new/*"
          } }
        },
        {
          Sid      = "ReadRecoveryObjects"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:GetObjectVersion"]
          Resource = "arn:aws:s3:::test-etcd-backups-123456789012-us-east-1/openclaw-enterprise/new/*"
        },
        {
          Sid      = "PublishKmsRecoveryObjects"
          Effect   = "Allow"
          Action   = ["s3:PutObject"]
          Resource = "arn:aws:s3:::test-etcd-backups-123456789012-us-east-1/openclaw-enterprise/new/*"
          Condition = { StringEqualsIfExists = {
            "s3:x-amz-server-side-encryption" = "aws:kms"
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
              "kms:EncryptionContext:aws:s3:arn" = "arn:aws:s3:::test-etcd-backups-123456789012-us-east-1"
            }
          }
        },
      ]
    )
    error_message = "Publisher grants must stay on the new prefix and bucket-key-scoped KMS use, without delete or legacy access."
  }
}

run "rejects_unprotected_publisher_ref" {
  command = plan
  variables {
    publisher = {
      role_name     = "homelab-oce-recovery-publisher"
      object_prefix = "openclaw-enterprise/new/"
      subject       = "repo:Stuhlmuller/homelab:environment:homelab-production"
      workflow      = "OpenClaw Enterprise Recovery Publication"
      ref           = "refs/heads/feature"
      repository_id = 973476220
    }
  }
  expect_failures = [var.publisher]
}

run "rejects_wrong_identity" {
  command = plan
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "999999999999" }
  }
  expect_failures = [aws_s3_bucket.backup]
}

run "rejects_wrong_provider_region" {
  command = plan
  override_data {
    target = data.aws_region.current
    values = { region = "us-west-2" }
  }
  expect_failures = [aws_s3_bucket.backup]
}

run "rejects_shared_bucket_name" {
  command = plan
  variables {
    bucket_name = "existing-shared-state-bucket"
  }
  expect_failures = [aws_s3_bucket.backup]
}
