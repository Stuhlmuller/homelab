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

variables {
  aws_region           = "us-west-2"
  create_kms_key       = true
  kms_key_id           = "alias/homelab-test"
  parameter_kms_key_id = null
  parameters = {
    "/homelab/test/encryption-key" = {
      description = "Test hexadecimal key."
      generated = {
        kind   = "hex"
        length = 32
      }
    }
  }
}

run "uses_random_id_for_hex_values" {
  command = plan

  assert {
    condition = (
      random_id.generated["/homelab/test/encryption-key"].byte_length == 32 &&
      length(random_id.generated) == 1 &&
      length(random_password.generated) == 0
    )
    error_message = "Hex SSM values must use random_id with the requested byte length."
  }
}
