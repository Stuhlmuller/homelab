provider "aws" {
  region                      = "us-west-2"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

provider "openrouter" {
  api_key = "test"
}

override_resource {
  target = openrouter_api_key.this
  values = { key = "sk-or-fixture-not-a-real-key" }
}

variables {
  key_name       = "homelab-litellm"
  parameter_name = "/homelab/litellm/openrouter-api-key"
  kms_key_id     = "alias/aws/ssm"
  tags           = { Project = "test" }
}

run "stores_issued_key_as_encrypted_parameter" {
  command = plan

  assert {
    condition = (
      openrouter_api_key.this.name == "homelab-litellm" &&
      !openrouter_api_key.this.disabled &&
      aws_ssm_parameter.this.name == "/homelab/litellm/openrouter-api-key" &&
      aws_ssm_parameter.this.type == "SecureString" &&
      aws_ssm_parameter.this.key_id == "alias/aws/ssm" &&
      aws_ssm_parameter.this.value == "sk-or-fixture-not-a-real-key"
    )
    error_message = "The issued key must flow directly into the encrypted LiteLLM SSM parameter."
  }
}
