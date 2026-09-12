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

variables {
  additional_kms_key_aliases            = []
  apply_role_name                       = "test-apply"
  aws_region                            = "us-west-2"
  external_secrets_boundary_policy_name = "test"
  external_secrets_user_name            = "test"
  kms_key_id                            = "alias/test"
  parameter_reader_group_name           = "test-readers"
  parameter_reader_policy_name_prefix   = "test-reader-"
  policy_name                           = "test-policy"
}

override_data {
  target = data.aws_kms_alias.additional_runtime_secret
  values = { target_key_arn = "arn:aws:kms:us-west-2:123456789012:key/managed" }
}

run "migration_allows_only_both_exact_keys" {
  command = plan

  variables {
    additional_kms_key_aliases = ["alias/aws/ssm"]
  }

  plan_options {
    refresh = false
    target  = [data.aws_iam_policy_document.external_secrets_boundary]
  }

  assert {
    condition = toset(jsondecode(data.aws_iam_policy_document.external_secrets_boundary.json).Statement[2].Resource) == toset([
      "arn:aws:kms:us-west-2:123456789012:key/test",
      "arn:aws:kms:us-west-2:123456789012:key/managed",
    ])
    error_message = "Migration must allow only the two resolved keys, never a KMS wildcard."
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
