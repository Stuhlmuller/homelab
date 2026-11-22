terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.65.0"
    }
  }
}

provider "aws" {
  region              = local.region
  allowed_account_ids = [local.account_id]
}

locals {
  account_id = "716182248480"
  region     = "us-west-2"
  models = toset([
    "amazon.nova-lite-v1:0",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
  ])
  destinations = ["us-east-1", "us-east-2", local.region]
  profiles     = { for model in local.models : model => "arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/us.${model}" }
  invoke       = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
  tags         = { Project = "homelab", Purpose = "litellm-bedrock" }
}

resource "aws_iam_user" "gateway" {
  # checkov:skip=CKV_AWS_273: The Talos issuer is private. This non-human caller has no login profile.
  name = "homelab-litellm-bedrock"
  path = "/homelab/"
  tags = local.tags
}

resource "aws_iam_user_policy" "gateway" {
  # checkov:skip=CKV_AWS_40: This policy is exclusive to a single non-human inference client.
  name = "invoke-us-chat-profiles"
  user = aws_iam_user.gateway.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [{
        Effect   = "Allow"
        Action   = local.invoke
        Resource = values(local.profiles)
      }],
      [for model, profile in local.profiles : {
        Effect   = "Allow"
        Action   = local.invoke
        Resource = [for region in local.destinations : "arn:aws:bedrock:${region}::foundation-model/${model}"]
        Condition = {
          StringEquals = { "bedrock:InferenceProfileArn" = profile }
        }
      }]
    )
  })
}

resource "aws_iam_access_key" "gateway" {
  user = aws_iam_user.gateway.name
}

resource "aws_ssm_parameter" "credentials" {
  name        = "/homelab/litellm/bedrock-credentials"
  description = "Dedicated LiteLLM Bedrock shared credentials profile."
  type        = "SecureString"
  key_id      = "alias/aws/ssm"
  tags        = local.tags
  value       = <<-INI
    [litellm-bedrock]
    aws_access_key_id = ${aws_iam_access_key.gateway.id}
    aws_secret_access_key = ${aws_iam_access_key.gateway.secret}
  INI
}
