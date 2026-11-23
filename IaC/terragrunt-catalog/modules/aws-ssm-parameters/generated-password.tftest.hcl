mock_provider "aws" {}

variables {
  aws_region = "us-west-2"
  kms_key_id = "alias/test"
  parameters = {
    "/homelab/adguard/admin-password" = {
      description   = "AdGuard administrator credential fixture."
      reader_access = true
      generated = {
        length  = 32
        special = false
      }
    }
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

run "adguard_bcrypt_credential_and_exact_reader" {
  command = plan

  assert {
    condition = (
      random_password.generated["/homelab/adguard/admin-password"].length == 32 &&
      random_password.generated["/homelab/adguard/admin-password"].lower &&
      random_password.generated["/homelab/adguard/admin-password"].upper &&
      random_password.generated["/homelab/adguard/admin-password"].numeric &&
      !random_password.generated["/homelab/adguard/admin-password"].special &&
      var.parameters["/homelab/adguard/admin-password"].generated.prefix == "" &&
      aws_ssm_parameter.generated["/homelab/adguard/admin-password"].type == "SecureString"
    )
    error_message = "AdGuard requires a generated 32-byte ASCII credential below bcrypt's 72-byte limit, stored only as SecureString."
  }

  assert {
    condition = local.parameter_reader_names == toset([
      "/homelab/adguard/admin-password", "/homelab/test/code", "/homelab/test/password",
    ])
    error_message = "The reader grant must contain exact declared parameter names, with no wildcard or unrelated addition."
  }
}
