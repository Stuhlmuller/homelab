# Plan-only: no AWS API reads or IAM mutation.
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

override_resource {
  target = aws_iam_policy.boundary
  values = { arn = "arn:aws:iam::123456789012:policy/homelab-platform-etcd-receipt-publisher-boundary" }
}

variables {
  account_id     = "123456789012"
  region         = "us-east-1"
  etcd_bucket    = "homelab-etcd-backups-123456789012-us-east-1"
  receipt_bucket = "homelab-application-backups-123456789012-us-east-1"
  tags           = { Project = "test" }
}

run "only_protected_production_workflow_can_assume_role" {
  command = plan

  assert {
    condition = (
      aws_iam_role.publisher.name == "homelab-platform-etcd-receipt-publisher" &&
      aws_iam_role.publisher.max_session_duration == 3600 &&
      aws_iam_role.publisher.permissions_boundary == aws_iam_policy.boundary.arn &&
      jsondecode(aws_iam_role_policy.publisher.policy) == jsondecode(aws_iam_policy.boundary.policy) &&
      jsondecode(aws_iam_role.publisher.assume_role_policy).Statement == [{
        Effect = "Allow"
        Action = "sts:AssumeRoleWithWebIdentity"
        Principal = {
          Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
        }
        Condition = { StringEquals = {
          "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub"           = "repo:Stuhlmuller/homelab:environment:homelab-production"
          "token.actions.githubusercontent.com:workflow"      = "Platform Etcd Prerequisite Publication"
          "token.actions.githubusercontent.com:ref"           = "refs/heads/main"
          "token.actions.githubusercontent.com:repository_id" = "973476220"
          "token.actions.githubusercontent.com:actor_id"      = "57728706"
        } }
      }]
    )
    error_message = "Only the fixed protected main workflow may assume the bounded role."
  }
}

run "raw_read_and_receipt_write_stay_in_separate_prefixes" {
  command = plan

  assert {
    condition = (
      length(jsondecode(aws_iam_policy.boundary.policy).Statement) == 8 &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[0].Action == ["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"] &&
      toset(jsondecode(aws_iam_policy.boundary.policy).Statement[0].Resource) == toset([
        "arn:aws:s3:::homelab-etcd-backups-123456789012-us-east-1",
        "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1",
      ]) &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[1].Action == ["s3:ListBucketVersions"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[1].Resource == "arn:aws:s3:::homelab-etcd-backups-123456789012-us-east-1" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[1].Condition.StringLike["s3:prefix"] == "etcd/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[2].Action == ["s3:GetObject", "s3:GetObjectVersion"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[2].Resource == "arn:aws:s3:::homelab-etcd-backups-123456789012-us-east-1/etcd/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[3].Action == ["s3:ListBucketVersions"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[3].Resource == "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[3].Condition.StringLike["s3:prefix"] == "openclaw-enterprise/platform/receipts/*/off-node-etcd-backup/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[4].Action == ["s3:GetObject", "s3:GetObjectVersion"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[4].Resource == "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1/openclaw-enterprise/platform/receipts/*/off-node-etcd-backup/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[5].Action == ["s3:PutObject"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[5].Resource == "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1/openclaw-enterprise/platform/receipts/*/off-node-etcd-backup/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[5].Condition.StringEquals["s3:x-amz-server-side-encryption"] == "aws:kms" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[6].Action == ["kms:GenerateDataKey", "kms:Decrypt"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[6].Resource == "arn:aws:kms:us-east-1:123456789012:key/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[6].Condition["ForAnyValue:StringEquals"]["kms:ResourceAliases"] == "alias/aws/s3" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[6].Condition.StringEquals["kms:ViaService"] == "s3.us-east-1.amazonaws.com" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[6].Condition.StringEquals["kms:EncryptionContext:aws:s3:arn"] == "arn:aws:s3:::homelab-etcd-backups-123456789012-us-east-1" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[7].Action == ["kms:GenerateDataKey", "kms:Decrypt"] &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[7].Resource == "arn:aws:kms:us-east-1:123456789012:key/*" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[7].Condition["ForAnyValue:StringEquals"]["kms:ResourceAliases"] == "alias/aws/s3" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[7].Condition.StringEquals["kms:ViaService"] == "s3.us-east-1.amazonaws.com" &&
      jsondecode(aws_iam_policy.boundary.policy).Statement[7].Condition.StringEquals["kms:EncryptionContext:aws:s3:arn"] == "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1"
    )
    error_message = "Raw etcd bytes must be read-only; only the exact prerequisite prefix may be written."
  }
}
