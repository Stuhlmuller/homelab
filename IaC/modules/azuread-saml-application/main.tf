data "azuread_client_config" "current" {}

data "azuread_user" "allowed" {
  for_each            = var.allowed_user_principal_names
  user_principal_name = each.value
}

resource "azuread_application" "this" {
  display_name            = var.display_name
  prevent_duplicate_names = true
  sign_in_audience        = "AzureADMyOrg"
  identifier_uris         = [var.entity_id]
  owners                  = [data.azuread_client_config.current.object_id]

  web {
    homepage_url  = var.login_url
    redirect_uris = [var.assertion_consumer_service_url]

    implicit_grant {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }
}

resource "azuread_service_principal" "this" {
  client_id                     = azuread_application.this.client_id
  owners                        = [data.azuread_client_config.current.object_id]
  app_role_assignment_required  = true
  preferred_single_sign_on_mode = "saml"
  login_url                     = var.login_url

  feature_tags {
    enterprise = true
  }
}

resource "azuread_service_principal_token_signing_certificate" "this" {
  service_principal_id = azuread_service_principal.this.id
  display_name         = "CN=${var.display_name} SAML signing"
  end_date             = var.signing_certificate_end_date

  lifecycle {
    create_before_destroy = true
  }
}

# The AzureAD certificate resource creates the key but does not select it for
# SAML signing. Microsoft Graph owns only this missing property, not the SP.
resource "msgraph_update_resource" "signing_certificate" {
  url         = "servicePrincipals/${azuread_service_principal.this.object_id}"
  api_version = "v1.0"
  body = {
    preferredTokenSigningKeyThumbprint = azuread_service_principal_token_signing_certificate.this.thumbprint
  }
  read_query_parameters = {
    "$select" = ["id,preferredTokenSigningKeyThumbprint"]
  }
  ignore_missing_property = false
}

resource "azuread_app_role_assignment" "allowed" {
  for_each            = data.azuread_user.allowed
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = each.value.object_id
  resource_object_id  = azuread_service_principal.this.object_id
}
