provider "aws" {
  region = var.aws_region
}
provider "azuread" {}

data "azuread_user" "application_owner" {
  object_id = var.owner_object_id
}
data "azuread_service_principal" "terraform_apply" {
  display_name = var.owner_service_principal_name
}
data "azuread_client_config" "current" {}

resource "azuread_application_password" "sso" {
  application_id    = azuread_application.this.id
  display_name      = var.credential_display_name
  end_date_relative = "8760h"
}

locals {
  sso_values = {
    client_id     = azuread_application.this.client_id
    client_secret = azuread_application_password.sso.value
    tenant_id     = data.azuread_client_config.current.tenant_id
    auth_url      = format("https://login.microsoftonline.com/%s/oauth2/v2.0/authorize", data.azuread_client_config.current.tenant_id)
    token_url     = format("https://login.microsoftonline.com/%s/oauth2/v2.0/token", data.azuread_client_config.current.tenant_id)
    issuer_url    = format("https://login.microsoftonline.com/%s/v2.0", data.azuread_client_config.current.tenant_id)
  }
}

resource "aws_ssm_parameter" "sso" {
  for_each = var.sso_parameters

  region      = var.aws_region
  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = local.sso_values[each.value.value_key]
  key_id      = var.parameter_kms_key_id
  tier        = "Standard"
  tags        = var.parameter_tags
}
