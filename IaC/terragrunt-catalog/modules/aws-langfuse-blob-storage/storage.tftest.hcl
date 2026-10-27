provider "aws" {
  region                      = "us-west-2"
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
  values = { region = "us-west-2" }
}

variables {
  bucket_name          = "test-langfuse-123456789012-us-west-2"
  expected_account_id  = "123456789012"
  aws_region           = "us-west-2"
  parameter_kms_key_id = "alias/aws/ssm"
  tags                 = { Project = "test" }
}

run "keeps_raw_events_private_and_bounded" {
  command = plan

  assert {
    condition = (
      !aws_s3_bucket.langfuse.force_destroy &&
      aws_s3_bucket_versioning.langfuse.versioning_configuration[0].status == "Enabled" &&
      aws_s3_bucket_public_access_block.langfuse.block_public_acls &&
      aws_s3_bucket_public_access_block.langfuse.block_public_policy &&
      aws_s3_bucket_public_access_block.langfuse.ignore_public_acls &&
      aws_s3_bucket_public_access_block.langfuse.restrict_public_buckets &&
      aws_s3_bucket_lifecycle_configuration.langfuse.rule[0].expiration[0].days == 30 &&
      aws_s3_bucket_lifecycle_configuration.langfuse.rule[0].noncurrent_version_expiration[0].noncurrent_days == 7
    )
    error_message = "Langfuse raw events must stay private, versioned, and bounded to the declared 30-day pilot retention."
  }

  assert {
    condition = (
      length(jsondecode(aws_iam_user_policy.langfuse.policy).Statement) == 2 &&
      alltrue([for statement in jsondecode(aws_iam_user_policy.langfuse.policy).Statement :
        statement.Sid == "ListLangfuseBlobBucket" ? (
          statement.Effect == "Allow" &&
          toset(statement.Action) == toset(["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"]) &&
          statement.Resource == "arn:aws:s3:::test-langfuse-123456789012-us-west-2"
          ) : statement.Sid == "WriteLangfuseBlobObjects" ? (
          statement.Effect == "Allow" &&
          toset(statement.Action) == toset(["s3:AbortMultipartUpload", "s3:DeleteObject", "s3:GetObject", "s3:ListMultipartUploadParts", "s3:PutObject"]) &&
          statement.Resource == "arn:aws:s3:::test-langfuse-123456789012-us-west-2/*"
        ) : false
      ])
    )
    error_message = "The Langfuse runtime user must remain scoped to its dedicated blob bucket."
  }
}
