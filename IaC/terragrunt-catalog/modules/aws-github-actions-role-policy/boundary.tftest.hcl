# Evaluate the real provider-generated policy offline; never apply IAM resources.
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
  target = data.aws_kms_alias.runtime_secret
  values = { target_key_arn = "arn:aws:kms:us-west-2:123456789012:key/test" }
}

override_data {
  target = data.aws_kms_alias.langfuse_s3
  values = { target_key_arn = "arn:aws:kms:us-west-2:123456789012:key/langfuse-s3-test" }
}

override_data {
  target = data.aws_iam_openid_connect_provider.github_actions
  values = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
}

override_resource {
  target = aws_iam_policy.langfuse_raw_backup_boundary
  values = { arn = "arn:aws:iam::123456789012:policy/homelab-langfuse-raw-backup-boundary" }
}

variables {
  apply_role_name                       = "test-apply"
  aws_region                            = "us-west-2"
  external_secrets_boundary_policy_name = "test"
  external_secrets_user_name            = "test"
  kms_key_id                            = "alias/test"
  langfuse_bucket_name                  = "homelab-langfuse-123456789012-us-west-2"
  application_backup_bucket_name        = "homelab-application-backups-123456789012-us-east-1"
  parameter_reader_group_name           = "test-readers"
  parameter_reader_policy_name_prefix   = "test-reader-"
  policy_name                           = "test-policy"
}

run "dedicated_raw_backup_role_is_production_workflow_only" {
  command = plan

  plan_options {
    refresh = false
    target  = [aws_iam_role.langfuse_raw_backup]
  }

  assert {
    condition = (
      aws_iam_role.langfuse_raw_backup.name == "homelab-langfuse-raw-backup" &&
      aws_iam_role.langfuse_raw_backup.max_session_duration == 21600 &&
      aws_iam_role.langfuse_raw_backup.permissions_boundary == aws_iam_policy.langfuse_raw_backup_boundary.arn &&
      jsondecode(data.aws_iam_policy_document.langfuse_raw_backup_assume_role.json).Statement[0].Condition.StringEquals == {
        "token.actions.githubusercontent.com:aud"           = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub"           = "repo:Stuhlmuller/homelab:environment:homelab-production"
        "token.actions.githubusercontent.com:workflow"      = "Langfuse Raw Version Backup"
        "token.actions.githubusercontent.com:ref"           = "refs/heads/main"
        "token.actions.githubusercontent.com:repository_id" = "973476220"
      }
    )
    error_message = "The raw backup role must require the exact protected production workflow and a permissions boundary."
  }
}

run "dedicated_raw_backup_role_has_only_two_bucket_scopes" {
  command = plan

  plan_options {
    refresh = false
    target  = [aws_iam_role_policy.langfuse_raw_backup]
  }

  assert {
    condition = (
      aws_iam_role_policy.langfuse_raw_backup.role == "homelab-langfuse-raw-backup" &&
      jsondecode(aws_iam_role_policy.langfuse_raw_backup.policy) == jsondecode(aws_iam_policy.langfuse_raw_backup_boundary.policy) &&
      toset([for statement in jsondecode(data.aws_iam_policy_document.langfuse_raw_backup.json).Statement : statement.Sid]) == toset([
        "InspectRawAndBackupBuckets", "ListLangfuseRawVersions",
        "ReadLangfuseRawVersions", "WriteAndReadLangfuseBackupVersions",
        "DecryptLangfuseRawVersions", "EncryptAndDecryptLangfuseBackupVersions",
      ]) &&
      alltrue([for statement in jsondecode(data.aws_iam_policy_document.langfuse_raw_backup.json).Statement :
        statement.Effect == "Allow" &&
        !contains(flatten([statement.Action]), "s3:DeleteObject") &&
        !contains(flatten([statement.Action]), "s3:DeleteObjectVersion") &&
        !contains(flatten([statement.Action]), "kms:CreateGrant")
      ]) &&
      toset(flatten([for statement in jsondecode(data.aws_iam_policy_document.langfuse_raw_backup.json).Statement : flatten([statement.Action])])) == toset([
        "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration", "s3:ListBucketVersions",
        "s3:GetObjectVersion", "s3:PutObject", "kms:Decrypt", "kms:GenerateDataKey",
      ]) &&
      [for statement in jsondecode(data.aws_iam_policy_document.langfuse_raw_backup.json).Statement : statement.Resource if statement.Sid == "WriteAndReadLangfuseBackupVersions"][0] ==
      "arn:aws:s3:::homelab-application-backups-123456789012-us-east-1/langfuse/raw-versions/*"
    )
    error_message = "The raw backup role must read only Langfuse source versions and write only its offsite prefix without delete or grant access."
  }
}

run "legacy_archive_role_session_outlives_job" {
  command = plan

  plan_options {
    refresh = false
    target  = [aws_iam_role.github_actions]
  }

  assert {
    condition     = aws_iam_role.github_actions.max_session_duration == 25200
    error_message = "The legacy archive role session must outlive the protected six-hour job by one hour."
  }
}

run "apply_role_describes_only_current_runtime_key" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.parameter_reader_administration]
  }

  assert {
    condition = [
      for statement in jsondecode(data.aws_iam_policy_document.parameter_reader_administration.json).Statement : statement
      if anytrue([for action in flatten([statement.Action]) : startswith(lower(action), "kms:") || action == "*"])
      ] == [{
        Sid      = "DescribeRuntimeSecretKey"
        Effect   = "Allow"
        Action   = "kms:DescribeKey"
        Resource = "arn:aws:kms:us-west-2:123456789012:key/test"
    }]
    error_message = "The apply role must gain only DescribeKey on the current runtime-secret key, with no cryptographic, administrative, or wildcard permissions."
  }
}

run "apply_role_reads_only_langfuse_blob_storage_identity" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.parameter_reader_administration]
  }

  assert {
    condition = [
      for statement in jsondecode(data.aws_iam_policy_document.parameter_reader_administration.json).Statement : {
        Sid       = statement.Sid
        Effect    = statement.Effect
        Actions   = toset(flatten([statement.Action]))
        Resources = toset(flatten([statement.Resource]))
      }
      if anytrue([
        for resource in flatten([statement.Resource]) :
        resource == "*" || strcontains(resource, ":user/")
      ])
      ] == [{
        Sid    = "ReadLangfuseBlobStorageIdentity"
        Effect = "Allow"
        Actions = toset([
          "iam:GetUser",
          "iam:GetUserPolicy",
          "iam:ListAccessKeys",
        ])
        Resources = toset([
          "arn:aws:iam::123456789012:user/homelab/homelab-langfuse-s3",
        ])
    }]
    error_message = "The apply role may read only the exact Langfuse S3 user's metadata; it must not gain wildcard or IAM write, tag, rotation, or other-user access."
  }
}

run "dedicated_inventory_role_trust_excludes_plan_prs_and_other_repos" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.langfuse_raw_inventory_assume_role]
  }

  assert {
    condition = (
      jsondecode(data.aws_iam_policy_document.langfuse_raw_inventory_assume_role.json).Statement == [{
        Effect = "Allow"
        Action = "sts:AssumeRoleWithWebIdentity"
        Principal = {
          Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
        }
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = "repo:Stuhlmuller/homelab:environment:homelab-production"
          }
        }
      }] &&
      alltrue([for subject in [
        "repo:Stuhlmuller/homelab:environment:homelab-plan",
        "repo:Stuhlmuller/homelab:ref:refs/heads/main",
        "repo:Stuhlmuller/homelab:ref:refs/heads/feature",
        "repo:Stuhlmuller/github-iac:environment:github-iac-production",
        "repo:Other/homelab:environment:homelab-production",
      ] : !contains(flatten([jsondecode(data.aws_iam_policy_document.langfuse_raw_inventory_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]]), subject)])
    )
    error_message = "The inventory role must trust only the homelab production environment, never an unprotected plan, branch, or another repository."
  }
}

run "dedicated_inventory_role_reads_only_exact_langfuse_raw_versions" {
  command = plan

  plan_options {
    refresh = false
    target  = [aws_iam_role_policy.langfuse_raw_inventory]
  }

  assert {
    condition = (
      aws_iam_role.langfuse_raw_inventory.name == "homelab-langfuse-raw-inventory" &&
      aws_iam_role.langfuse_raw_inventory.max_session_duration == 7200 &&
      aws_iam_role_policy.langfuse_raw_inventory.name == "langfuse-raw-version-inventory" &&
      aws_iam_role_policy.langfuse_raw_inventory.role == "homelab-langfuse-raw-inventory" &&
      [for statement in jsondecode(aws_iam_role_policy.langfuse_raw_inventory.policy).Statement : {
        Sid       = statement.Sid
        Effect    = statement.Effect
        Actions   = toset(flatten([statement.Action]))
        Resources = toset(flatten([statement.Resource]))
        Condition = try(statement.Condition, {})
        }] == [
        {
          Sid       = "InspectLangfuseRawBucket"
          Effect    = "Allow"
          Actions   = toset(["s3:GetBucketVersioning", "s3:GetEncryptionConfiguration", "s3:ListBucketVersions"])
          Resources = toset(["arn:aws:s3:::homelab-langfuse-123456789012-us-west-2"])
          Condition = {}
        },
        {
          Sid       = "ReadLangfuseRawVersions"
          Effect    = "Allow"
          Actions   = toset(["s3:GetObjectVersion"])
          Resources = toset(["arn:aws:s3:::homelab-langfuse-123456789012-us-west-2/*"])
          Condition = {}
        },
        {
          Sid       = "DecryptLangfuseRawVersions"
          Effect    = "Allow"
          Actions   = toset(["kms:Decrypt"])
          Resources = toset(["arn:aws:kms:us-west-2:123456789012:key/langfuse-s3-test"])
          Condition = {
            StringEquals = {
              "kms:ViaService"                   = "s3.us-west-2.amazonaws.com"
              "kms:EncryptionContext:aws:s3:arn" = "arn:aws:s3:::homelab-langfuse-123456789012-us-west-2"
            }
          }
        },
      ]
    )
    error_message = "The protected inventory role may read only exact Langfuse versions and decrypt only through S3 for that bucket."
  }
}

run "rejects_other_langfuse_bucket_owner" {
  command = plan

  variables {
    langfuse_bucket_name = "homelab-langfuse-999999999999-us-west-2"
  }

  plan_options {
    refresh = false
    target  = [aws_iam_role_policy.langfuse_raw_inventory]
  }

  expect_failures = [aws_iam_role_policy.langfuse_raw_inventory]
}

run "operator_role_excludes_companion_renovate" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.github_actions_assume_role]
  }

  assert {
    condition = toset(jsondecode(data.aws_iam_policy_document.github_actions_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == toset([
      "repo:Stuhlmuller/github-iac:environment:github-iac-plan",
      "repo:Stuhlmuller/github-iac:environment:github-iac-production",
      "repo:Stuhlmuller/homelab:environment:homelab-plan",
      "repo:Stuhlmuller/homelab:environment:homelab-production",
    ])
    error_message = "The operator apply role must not trust the companion Renovate repository after credential transfer."
  }
}

run "temporary_credentials_and_forward_access_sessions" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.external_secrets_boundary]
  }

  assert {
    condition = alltrue([
      for context in [
        { temporary = false, forwarded = false, denied = false },
        { temporary = true, forwarded = false, denied = true },
        { temporary = false, forwarded = true, denied = false },
        { temporary = true, forwarded = true, denied = false },
        ] : (
        (!context.temporary == tobool(jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[0].Condition.Null["aws:TokenIssueTime"])) &&
        try(context.forwarded == tobool(jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[0].Condition.Bool["aws:ViaAWSService"]), true)
      ) == context.denied
    ])
    error_message = "Temporary direct requests must be denied; long-term credentials and AWS forward access sessions must not match the deny."
  }

  assert {
    condition     = jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[0].Effect == "Deny" && jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[0].Action == "*" && jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[0].Resource == "*"
    error_message = "The temporary-session restriction must remain an explicit deny covering every direct action and resource."
  }

  assert {
    condition = (
      jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[2].Effect == "Allow" &&
      toset(jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[2].Action) == toset(["kms:Decrypt", "kms:DescribeKey"]) &&
      jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[2].Resource == "arn:aws:kms:us-west-2:123456789012:key/test"
    )
    error_message = "Forwarded SSM decrypts must remain allowed only for the runtime-secret KMS key."
  }
}
