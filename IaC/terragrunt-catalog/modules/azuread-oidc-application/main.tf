resource "azuread_application" "this" {
  description                    = var.description
  device_only_auth_enabled       = var.device_only_auth_enabled
  display_name                   = var.display_name
  fallback_public_client_enabled = var.fallback_public_client_enabled
  group_membership_claims        = var.group_membership_claims
  identifier_uris                = var.identifier_uris
  logo_image                     = var.logo_image
  marketing_url                  = var.marketing_url
  notes                          = var.notes
  oauth2_post_response_required  = var.oauth2_post_response_required
  owners                         = [data.azuread_user.application_owner.object_id, data.azuread_service_principal.terraform_apply.object_id]
  prevent_duplicate_names        = var.prevent_duplicate_names
  privacy_statement_url          = var.privacy_statement_url
  service_management_reference   = var.service_management_reference
  sign_in_audience               = var.sign_in_audience
  support_url                    = var.support_url
  tags                           = var.tags
  template_id                    = var.template_id
  terms_of_service_url           = var.terms_of_service_url

  dynamic "api" {
    for_each = var.api != null ? [var.api] : []
    content {
      known_client_applications      = try(api.value.known_client_applications, null)
      mapped_claims_enabled          = try(api.value.mapped_claims_enabled, null)
      requested_access_token_version = try(api.value.requested_access_token_version, null)

      dynamic "oauth2_permission_scope" {
        for_each = try(api.value.oauth2_permission_scopes, [])
        content {
          admin_consent_description  = oauth2_permission_scope.value.admin_consent_description
          admin_consent_display_name = oauth2_permission_scope.value.admin_consent_display_name
          enabled                    = try(oauth2_permission_scope.value.enabled, true)
          id                         = oauth2_permission_scope.value.id
          type                       = oauth2_permission_scope.value.type
          user_consent_description   = try(oauth2_permission_scope.value.user_consent_description, null)
          user_consent_display_name  = try(oauth2_permission_scope.value.user_consent_display_name, null)
          value                      = try(oauth2_permission_scope.value.value, null)
        }
      }
    }
  }

  dynamic "app_role" {
    for_each = var.app_roles
    content {
      allowed_member_types = app_role.value.allowed_member_types
      description          = app_role.value.description
      display_name         = app_role.value.display_name
      enabled              = try(app_role.value.enabled, true)
      id                   = app_role.value.id
      value                = try(app_role.value.value, null)
    }
  }

  dynamic "feature_tags" {
    for_each = var.feature_tags != null ? [var.feature_tags] : []
    content {
      custom_single_sign_on = try(feature_tags.value.custom_single_sign_on, null)
      enterprise            = try(feature_tags.value.enterprise, null)
      gallery               = try(feature_tags.value.gallery, null)
      hide                  = try(feature_tags.value.hide, null)
    }
  }

  dynamic "optional_claims" {
    for_each = var.optional_claims != null ? [var.optional_claims] : []
    content {
      dynamic "access_token" {
        for_each = try(optional_claims.value.access_tokens, [])
        content {
          additional_properties = try(access_token.value.additional_properties, null)
          essential             = try(access_token.value.essential, null)
          name                  = access_token.value.name
          source                = try(access_token.value.source, null)
        }
      }

      dynamic "id_token" {
        for_each = try(optional_claims.value.id_tokens, [])
        content {
          additional_properties = try(id_token.value.additional_properties, null)
          essential             = try(id_token.value.essential, null)
          name                  = id_token.value.name
          source                = try(id_token.value.source, null)
        }
      }

      dynamic "saml2_token" {
        for_each = try(optional_claims.value.saml2_tokens, [])
        content {
          additional_properties = try(saml2_token.value.additional_properties, null)
          essential             = try(saml2_token.value.essential, null)
          name                  = saml2_token.value.name
          source                = try(saml2_token.value.source, null)
        }
      }
    }
  }

  dynamic "password" {
    for_each = var.password != null ? [var.password] : []
    content {
      display_name = password.value.display_name
      end_date     = try(password.value.end_date, null)
      start_date   = try(password.value.start_date, null)
    }
  }

  dynamic "public_client" {
    for_each = var.public_client != null ? [var.public_client] : []
    content {
      redirect_uris = try(public_client.value.redirect_uris, null)
    }
  }

  dynamic "required_resource_access" {
    for_each = var.required_resource_access
    content {
      resource_app_id = required_resource_access.value.resource_app_id

      dynamic "resource_access" {
        for_each = required_resource_access.value.resource_access
        content {
          id   = resource_access.value.id
          type = resource_access.value.type
        }
      }
    }
  }

  dynamic "single_page_application" {
    for_each = var.single_page_application != null ? [var.single_page_application] : []
    content {
      redirect_uris = try(single_page_application.value.redirect_uris, null)
    }
  }

  dynamic "web" {
    for_each = var.web != null ? [var.web] : []
    content {
      homepage_url  = try(web.value.homepage_url, null)
      logout_url    = try(web.value.logout_url, null)
      redirect_uris = try(web.value.redirect_uris, null)

      dynamic "implicit_grant" {
        for_each = try(web.value.implicit_grant, null) != null ? [web.value.implicit_grant] : []
        content {
          access_token_issuance_enabled = try(implicit_grant.value.access_token_issuance_enabled, null)
          id_token_issuance_enabled     = try(implicit_grant.value.id_token_issuance_enabled, null)
        }
      }
    }
  }

  dynamic "timeouts" {
    for_each = var.timeouts != null ? [var.timeouts] : []
    content {
      create = try(timeouts.value.create, null)
      delete = try(timeouts.value.delete, null)
      read   = try(timeouts.value.read, null)
      update = try(timeouts.value.update, null)
    }
  }

  lifecycle {
    precondition {
      condition     = var.tags == null || var.feature_tags == null
      error_message = "Use either tags or feature_tags, not both."
    }
  }
}
