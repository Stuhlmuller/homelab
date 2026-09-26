mock_provider "aws" {}

variables {
  aws_region = "us-west-2"
  kms_key_id = "alias/test"
  parameters = {
    "/homelab/test/code" = {
      description = "Numeric verification code."
      generated = {
        length  = 6
        lower   = false
        special = false
        upper   = false
      }
    }
    "/homelab/test/password" = {
      description = "Default password."
      generated   = {}
    }
  }
}

run "numeric_code_preserves_password_defaults" {
  command = plan

  assert {
    condition = (
      random_password.generated["/homelab/test/code"].length == 6 &&
      random_password.generated["/homelab/test/code"].numeric &&
      !random_password.generated["/homelab/test/code"].lower &&
      !random_password.generated["/homelab/test/code"].upper &&
      !random_password.generated["/homelab/test/code"].special
    )
    error_message = "Verification codes must contain exactly six digits."
  }

  assert {
    condition = (
      random_password.generated["/homelab/test/password"].length == 48 &&
      random_password.generated["/homelab/test/password"].numeric &&
      random_password.generated["/homelab/test/password"].lower &&
      random_password.generated["/homelab/test/password"].upper &&
      !random_password.generated["/homelab/test/password"].special
    )
    error_message = "Existing password character classes and length must remain unchanged."
  }
}
