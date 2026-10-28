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
  values = { account_id = "716182248480" }
}

override_data {
  target = data.aws_region.current
  values = { region = "us-east-1" }
}

variables {
  expected_account_id = "716182248480"
  aws_region          = "us-east-1"
  bucket_name         = "homelab-etcd-backups-716182248480-us-east-1"
  tags                = { Project = "test" }
}

run "only_protected_platform_stage_can_read_versioned_etcd" {
  command = plan

  assert {
    condition = (
      aws_iam_role.reader.name == "homelab-platform-etcd-reader" &&
      aws_iam_role.reader.max_session_duration == 9000 &&
      jsondecode(aws_iam_role.reader.assume_role_policy).Statement[0].Condition.StringEquals == {
        "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub"           = "repo:Stuhlmuller/homelab:environment:homelab-production"
        "token.actions.githubusercontent.com:workflow"      = "Platform Maintenance"
        "token.actions.githubusercontent.com:ref"           = "refs/heads/main"
        "token.actions.githubusercontent.com:repository_id" = "973476220"
        "token.actions.githubusercontent.com:actor_id"      = "57728706"
      }
    )
    error_message = "The reader must be a separate protected owner OIDC role with a session longer than the maintenance job."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.reader.policy) ==
      jsondecode(aws_iam_policy.boundary.policy) &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[0].Action ==
      ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[1].Condition.StringLike["s3:prefix"] == "etcd/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[2].Action == ["s3:GetObjectVersion"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[2].Resource ==
      "arn:aws:s3:::homelab-etcd-backups-716182248480-us-east-1/etcd/*" &&
      length(jsondecode(aws_iam_policy.boundary.policy).Statement) == 4
    )
    error_message = "The permissions boundary must allow only dedicated etcd version reads and bucket-key checksum inspection."
  }
}

run "rejects_a_different_aws_owner" {
  command = plan
  variables {
    expected_account_id = "123456789012"
    bucket_name         = "homelab-etcd-backups-123456789012-us-east-1"
  }
  expect_failures = [aws_iam_role.reader]
}
