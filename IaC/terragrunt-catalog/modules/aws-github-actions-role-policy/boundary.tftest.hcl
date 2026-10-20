# Evaluate the real provider-generated policy offline; never apply IAM resources.
provider "aws" {
  region                      = "us-west-2"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

provider "aws" {
  alias                       = "state"
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
  target = data.aws_kms_alias.runtime_secret
  values = { target_key_arn = "arn:aws:kms:us-west-2:123456789012:key/test" }
}

override_data {
  target = data.aws_kms_alias.state
  values = { target_key_arn = "arn:aws:kms:us-east-1:123456789012:key/state" }
}

override_data {
  target = data.aws_iam_openid_connect_provider.github_actions
  values = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
}

variables {
  apply_role_name                       = "test-apply"
  plan_role_name                        = "test-plan"
  state_bucket_name                     = "test-state"
  state_kms_key_id                      = "alias/test-state"
  backup_bucket_name                    = "test-backups"
  aws_region                            = "us-west-2"
  external_secrets_boundary_policy_name = "test"
  external_secrets_user_name            = "test"
  kms_key_id                            = "alias/test"
  parameter_reader_group_name           = "test-readers"
  parameter_reader_policy_name_prefix   = "test-reader-"
  policy_name                           = "test-policy"
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

run "plan_role_trusts_only_homelab_plan" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.github_actions_plan_assume_role]
  }

  assert {
    condition = (
      length(jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement) == 1 &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Principal.Federated == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:Stuhlmuller/homelab:environment:homelab-plan"
    )
    error_message = "The plan role must trust only the homelab-plan environment through GitHub OIDC."
  }
}

run "plan_role_can_only_read_its_state_and_backup_metadata" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.github_actions_plan]
  }

  assert {
    condition = {
      for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement.Sid => {
        actions   = toset(flatten([statement.Action]))
        resources = toset(flatten([statement.Resource]))
      }
      } == {
      LocateHomelabStateBucket = {
        actions   = toset(["s3:GetBucketLocation"])
        resources = toset(["arn:aws:s3:::test-state"])
      }
      ListHomelabStateBucket = {
        actions   = toset(["s3:ListBucket"])
        resources = toset(["arn:aws:s3:::test-state"])
      }
      ReadHomelabStateObjects = {
        actions = toset(["s3:GetObject"])
        resources = toset([
          "arn:aws:s3:::test-state/IaC/homelab/bootstrap/argocd/terraform.tfstate",
          "arn:aws:s3:::test-state/IaC/homelab/operator/application-backup-storage/terraform.tfstate",
          "arn:aws:s3:::test-state/IaC/homelab/live/argocd-apps/*/terraform.tfstate",
          "arn:aws:s3:::test-state/IaC/homelab/live/azuread-applications/*/terraform.tfstate",
        ])
      }
      InspectApplicationBackupBucket = {
        actions   = toset(["s3:Get*", "s3:List*"])
        resources = toset(["arn:aws:s3:::test-backups"])
      }
      ReadAzureadSsoParameters = {
        actions = toset(["ssm:GetParameter", "ssm:ListTagsForResource"])
        resources = toset([
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/allowed-organizations",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/auth-url",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/client-id",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/client-secret",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/token-url",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/client-id",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/client-secret",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/issuer-url",
          "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/tenant-id",
        ])
      }
      DescribeAzureadSsoParameters = {
        actions   = toset(["ssm:DescribeParameters"])
        resources = toset(["*"])
      }
      DecryptAzureadSsoParameters = {
        actions   = toset(["kms:Decrypt"])
        resources = toset(["arn:aws:kms:us-west-2:123456789012:key/test"])
      }
      ReadEncryptedStateAndWriteLocalPlans = {
        actions   = toset(["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey"])
        resources = toset(["arn:aws:kms:us-east-1:123456789012:key/state"])
      }
    }
    error_message = "The plan role may read only PR-planned state, backup-bucket metadata, generated SSO parameters, and the keys needed for local encrypted plans."
  }

  assert {
    condition = [
      for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement.Condition.StringLike["s3:prefix"]
      if statement.Sid == "ListHomelabStateBucket"
      ] == [[
        "IaC/homelab/bootstrap/argocd/*",
        "IaC/homelab/operator/application-backup-storage/*",
        "IaC/homelab/live/argocd-apps/*",
        "IaC/homelab/live/azuread-applications/*",
    ]]
    error_message = "The plan role must not list state outside PR-planned units."
  }

  assert {
    condition = (
      [for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DecryptAzureadSsoParameters"][0].Condition.StringEquals["kms:ViaService"] == "ssm.us-west-2.amazonaws.com" &&
      toset(flatten([[for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DecryptAzureadSsoParameters"][0].Condition.StringEquals["kms:EncryptionContext:PARAMETER_ARN"]])) == toset([
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/allowed-organizations",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/auth-url",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/client-id",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/client-secret",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/grafana/azuread/token-url",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/client-id",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/client-secret",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/issuer-url",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/octelium/entra/tenant-id",
      ])
    )
    error_message = "The plan role may decrypt only generated SSO parameters through SSM."
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
