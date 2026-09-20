terraform {
  required_version = ">= 1.9.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "signer_role_name" {
  type        = string
  description = "Existing protected publishing role allowed to sign with this key."
}

variable "tags" {
  type        = map(string)
  description = "Ownership tags."
}

data "aws_caller_identity" "current" {}
data "aws_iam_role" "signer" { name = var.signer_role_name }

data "aws_iam_policy_document" "key" {
  # checkov:skip=CKV_AWS_111: Account root retains KMS administration for recovery.
  # checkov:skip=CKV_AWS_109: Account root must retain key-policy administration.
  # checkov:skip=CKV_AWS_356: Resource * in a KMS key policy means only the attached key.
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
  statement {
    sid       = "ProtectedPublisherSigning"
    actions   = ["kms:Sign", "kms:Verify", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = [data.aws_iam_role.signer.arn]
    }
  }
}

resource "aws_kms_key" "signing" {
  # checkov:skip=CKV_AWS_7: AWS does not support automatic rotation for asymmetric keys; retain old public keys and rotate through a reviewed replacement.
  description              = "Private Harbor OCI signatures; key material never leaves KMS"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 30
  policy                   = data.aws_iam_policy_document.key.json
  tags                     = var.tags
  lifecycle { prevent_destroy = true }
}

resource "aws_kms_alias" "signing" {
  name          = "alias/homelab-harbor-signing"
  target_key_id = aws_kms_key.signing.key_id
}
