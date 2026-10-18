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
  target = data.aws_iam_openid_connect_provider.github_actions
  values = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
}

variables {
  apply_role_name                       = "test-apply"
  aws_region                            = "us-west-2"
  external_secrets_boundary_policy_name = "test"
  external_secrets_user_name            = "test"
  kms_key_id                            = "alias/test"
  parameter_reader_group_name           = "test-readers"
  parameter_reader_policy_name_prefix   = "test-reader-"
  policy_name                           = "test-policy"
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

run "renovate_transfer_trusts_only_companion_main" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.renovate_transfer_assume_role]
  }

  assert {
    condition = (
      length(jsondecode(data.aws_iam_policy_document.renovate_transfer_assume_role.json).Statement) == 1 &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer_assume_role.json).Statement[0].Effect == "Allow" &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer_assume_role.json).Statement[0].Action == "sts:AssumeRoleWithWebIdentity" &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer_assume_role.json).Statement[0].Principal.Federated == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:Stuhlmuller/renovate:ref:refs/heads/main"
    )
    error_message = "Renovate transfer must trust only GitHub OIDC from the companion repository's main branch."
  }
}

run "renovate_transfer_can_write_only_two_declared_parameters" {
  command = plan

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.renovate_transfer]
  }

  assert {
    condition = (
      length(jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement) == 2 &&
      alltrue([
        for statement in jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement :
        statement.Effect == "Allow"
      ]) &&
      toset(flatten([
        for statement in jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement :
        flatten([statement.Action])
      ])) == toset(["ssm:PutParameter", "kms:Encrypt"]) &&
      toset(flatten([
        for statement in jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement :
        flatten([statement.Resource]) if statement.Sid == "WriteRenovateAppCredentials"
        ])) == toset([
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/renovate/github-app/issuer-id",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/renovate/github-app/private-key",
      ]) &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement[1].Resource == "arn:aws:kms:us-west-2:123456789012:key/test" &&
      jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement[1].Condition.StringEquals["kms:ViaService"] == "ssm.us-west-2.amazonaws.com" &&
      toset(flatten([jsondecode(data.aws_iam_policy_document.renovate_transfer.json).Statement[1].Condition.StringEquals["kms:EncryptionContext:PARAMETER_ARN"]])) == toset([
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/renovate/github-app/issuer-id",
        "arn:aws:ssm:us-west-2:123456789012:parameter/homelab/renovate/github-app/private-key",
      ])
    )
    error_message = "Renovate transfer may only write its two declared parameters and encrypt their values through SSM."
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
