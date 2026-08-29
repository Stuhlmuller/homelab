provider "aws" {
  region                      = "us-west-2"
  access_key                  = "testing"
  secret_key                  = "testing"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

provider "aws" {
  alias                       = "state"
  region                      = "us-east-1"
  access_key                  = "testing"
  secret_key                  = "testing"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
    arn        = "arn:aws:iam::123456789012:user/testing"
    id         = "123456789012"
  }
}

override_data {
  target = data.aws_partition.current
  values = {
    dns_suffix = "amazonaws.com"
    partition  = "aws"
  }
}

override_data {
  target = data.aws_kms_alias.runtime_secret
  values = {
    target_key_arn = "arn:aws:kms:us-west-2:123456789012:key/runtime-secret"
  }
}

override_data {
  target = data.aws_kms_alias.state
  values = {
    target_key_arn = "arn:aws:kms:us-east-1:123456789012:key/state"
  }
}

override_data {
  target = data.aws_iam_openid_connect_provider.github_actions
  values = {
    arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  }
}

override_resource {
  target = aws_iam_policy.github_actions_plan
  values = {
    arn = "arn:aws:iam::123456789012:policy/homelab-github-terragrunt-plan-read-only"
  }
}

variables {
  apply_role_name = "Github-TF-State"
  aws_region      = "us-west-2"
  # checkov:skip=CKV_SECRET_6:Public IAM names used only by mocked policy tests.
  external_secrets_boundary_policy_name = "homelab-external-secrets-boundary"
  external_secrets_user_name            = "external-secrets_aws-ssm-auth"
  kms_key_id                            = "alias/homelab-opentofu"
  parameter_reader_group_name           = "homelab-ssm-parameter-readers"
  parameter_reader_policy_name_prefix   = "homelab-ssm-parameter-reader-"
  parameter_reader_policy_slot_count    = 10
  plan_policy_name                      = "homelab-github-terragrunt-plan-read-only"
  plan_role_name                        = "Github-Homelab-Plan"
  policy_name                           = "homelab-github-terragrunt-ssm-reader-policy-admin"
  state_bucket_name                     = "rstuhlmuller-aws-s3-use1-datalake"
  state_key_prefix                      = "IaC/homelab/live/argocd-apps"
}

run "plan_role_has_exact_trust_and_boundary" {
  command = plan

  assert {
    condition = (
      aws_iam_role.github_actions_plan.name == "Github-Homelab-Plan" &&
      aws_iam_role.github_actions_plan.permissions_boundary == "arn:aws:iam::123456789012:policy/homelab-github-terragrunt-plan-read-only" &&
      length(aws_iam_role_policy_attachments_exclusive.github_actions_plan.policy_arns) == 1 &&
      contains(aws_iam_role_policy_attachments_exclusive.github_actions_plan.policy_arns, "arn:aws:iam::123456789012:policy/homelab-github-terragrunt-plan-read-only") &&
      length(aws_iam_role_policies_exclusive.github_actions_plan.policy_names) == 0
    )
    error_message = "The plan role must use its sole managed policy as its permissions boundary and have no inline policies."
  }

  assert {
    condition = (
      length(jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement) == 1 &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Action == "sts:AssumeRoleWithWebIdentity" &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Effect == "Allow" &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Principal.Federated == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
      jsondecode(data.aws_iam_policy_document.github_actions_plan_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:Stuhlmuller/homelab:environment:homelab-plan"
    )
    error_message = "The plan role must trust only the homelab-plan environment in Stuhlmuller/homelab."
  }

  assert {
    condition = toset(jsondecode(data.aws_iam_policy_document.github_actions_assume_role.json).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == toset([
      "repo:Stuhlmuller/github-iac:environment:github-iac-plan",
      "repo:Stuhlmuller/github-iac:environment:github-iac-production",
      "repo:Stuhlmuller/homelab:environment:homelab-plan",
      "repo:Stuhlmuller/homelab:environment:homelab-production",
    ])
    error_message = "The bootstrap must temporarily preserve all four existing apply-role environment subjects."
  }
}

run "plan_policy_allows_only_state_reads_and_key_use" {
  command = plan

  assert {
    condition = toset([
      for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement.Sid
      ]) == toset([
      "DenyActionsOutsideReadOnlyPlan",
      "DenyKeyUseOutsideStateKey",
      "DenyStateBucketListingOutsideBucket",
      "DenyStateBucketListingOutsidePrefix",
      "DenyStateObjectReadsOutsidePrefix",
      "ListArgoCdApplicationStatePrefix",
      "ReadArgoCdApplicationStateObjects",
      "UseStateAndPlanEncryptionKey",
    ])
    error_message = "The plan policy must contain only the three exact allows and five explicit deny guards."
  }

  assert {
    condition = (
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ReadArgoCdApplicationStateObjects"]).Effect == "Allow" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ReadArgoCdApplicationStateObjects"]).Action == "s3:GetObject" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ReadArgoCdApplicationStateObjects"]).Resource == "arn:aws:s3:::rstuhlmuller-aws-s3-use1-datalake/IaC/homelab/live/argocd-apps/*"
    )
    error_message = "The plan policy must read objects only below the exact Argo CD Application state prefix."
  }

  assert {
    condition = (
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ListArgoCdApplicationStatePrefix"]).Effect == "Allow" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ListArgoCdApplicationStatePrefix"]).Action == "s3:ListBucket" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ListArgoCdApplicationStatePrefix"]).Resource == "arn:aws:s3:::rstuhlmuller-aws-s3-use1-datalake" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "ListArgoCdApplicationStatePrefix"]).Condition.StringLike["s3:prefix"] == "IaC/homelab/live/argocd-apps/*"
    )
    error_message = "The plan policy must list only the exact Argo CD Application state prefix."
  }

  assert {
    condition = (
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "UseStateAndPlanEncryptionKey"]).Effect == "Allow" &&
      toset(one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "UseStateAndPlanEncryptionKey"]).Action) == toset([
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey",
      ]) &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "UseStateAndPlanEncryptionKey"]).Resource == "arn:aws:kms:us-east-1:123456789012:key/state"
    )
    error_message = "The plan policy must use only the state KMS key for decrypt, describe, and data-key generation."
  }

  assert {
    condition = (
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateObjectReadsOutsidePrefix"]).Effect == "Deny" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateObjectReadsOutsidePrefix"]).Action == "s3:GetObject" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateObjectReadsOutsidePrefix"]).NotResource == "arn:aws:s3:::rstuhlmuller-aws-s3-use1-datalake/IaC/homelab/live/argocd-apps/*" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsideBucket"]).Effect == "Deny" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsideBucket"]).Action == "s3:ListBucket" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsideBucket"]).NotResource == "arn:aws:s3:::rstuhlmuller-aws-s3-use1-datalake" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsidePrefix"]).Effect == "Deny" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsidePrefix"]).Action == "s3:ListBucket" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsidePrefix"]).Resource == "arn:aws:s3:::rstuhlmuller-aws-s3-use1-datalake" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyStateBucketListingOutsidePrefix"]).Condition.StringNotLike["s3:prefix"] == "IaC/homelab/live/argocd-apps/*" &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyKeyUseOutsideStateKey"]).Effect == "Deny" &&
      toset(one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyKeyUseOutsideStateKey"]).Action) == toset([
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey",
      ]) &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyKeyUseOutsideStateKey"]).NotResource == "arn:aws:kms:us-east-1:123456789012:key/state"
    )
    error_message = "Explicit denies must block otherwise-allowed action names outside the exact bucket prefix and state key."
  }

  assert {
    condition = (
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyActionsOutsideReadOnlyPlan"]).Effect == "Deny" &&
      toset(one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyActionsOutsideReadOnlyPlan"]).NotAction) == toset([
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey",
        "s3:GetObject",
        "s3:ListBucket",
      ]) &&
      one([for statement in jsondecode(data.aws_iam_policy_document.github_actions_plan.json).Statement : statement if statement.Sid == "DenyActionsOutsideReadOnlyPlan"]).Resource == "*"
    )
    error_message = "The plan policy must explicitly deny every action outside the exact state-read and KMS-use set."
  }
}
