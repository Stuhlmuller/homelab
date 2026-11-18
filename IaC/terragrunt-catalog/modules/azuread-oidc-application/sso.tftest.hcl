mock_provider "aws" {}
mock_provider "azuread" {
  mock_resource "azuread_application" {
    defaults = { id = "/applications/00000000-0000-0000-0000-000000000004" }
  }
  mock_data "azuread_service_principal" {
    defaults = { object_id = "00000000-0000-0000-0000-000000000003" }
  }
}

variables {
  display_name                 = "fixture"
  aws_region                   = "us-west-2"
  owner_object_id              = "00000000-0000-0000-0000-000000000001"
  owner_service_principal_name = "fixture"
  credential_display_name      = "fixture-sso"
  parameter_kms_key_id         = "alias/test"
  parameter_tags               = { Project = "test" }
  sso_parameters = {
    "/test/auth-url"  = { description = "Authorization URL", value_key = "auth_url" }
    "/test/token-url" = { description = "Token URL", value_key = "token_url" }
  }
}
run "stable_parameter_contract" {
  command = plan
  override_data {
    target = data.azuread_client_config.current
    values = { tenant_id = "00000000-0000-0000-0000-000000000002" }
  }
  assert {
    condition     = aws_ssm_parameter.sso["/test/auth-url"].value == "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000002/oauth2/v2.0/authorize"
    error_message = "Authorization URL must retain the v2.0 endpoint."
  }
  assert {
    condition     = aws_ssm_parameter.sso["/test/token-url"].value == "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000002/oauth2/v2.0/token"
    error_message = "Token URL must retain the v2.0 endpoint."
  }
}
run "invalid_parameter_value" {
  command = plan
  variables {
    sso_parameters = { "/test/invalid" = { description = "Invalid", value_key = "unknown" } }
  }
  expect_failures = [var.sso_parameters]
}
