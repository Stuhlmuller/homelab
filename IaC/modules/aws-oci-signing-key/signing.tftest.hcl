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
  target = data.aws_iam_role.signer
  values = { arn = "arn:aws:iam::123456789012:role/Publisher" }
}
variables {
  signer_role_name = "Publisher"
  tags             = { Project = "test" }
}
run "private_signing_key" {
  command = plan
  assert {
    condition = (
      aws_kms_key.signing.key_usage == "SIGN_VERIFY" &&
      aws_kms_key.signing.customer_master_key_spec == "ECC_NIST_P256" &&
      aws_kms_key.signing.deletion_window_in_days == 30 &&
      aws_kms_alias.signing.name == "alias/homelab-harbor-signing" &&
      jsondecode(data.aws_iam_policy_document.key.json).Statement[1].Principal.AWS == "arn:aws:iam::123456789012:role/Publisher" &&
      toset(jsondecode(data.aws_iam_policy_document.key.json).Statement[1].Action) == toset(["kms:Sign", "kms:Verify", "kms:GetPublicKey", "kms:DescribeKey"])
    )
    error_message = "Signing must use the dedicated retained P-256 key and the exact publisher principal."
  }
}
