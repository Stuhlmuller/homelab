variable "kms_key_id" {
  description = "AWS KMS key ID for OpenTofu state encryption"
  type        = string
}

variable "kms_region" {
  description = "AWS region for the KMS key used by OpenTofu state encryption"
  type        = string
  default     = "us-west-2"
}

variable "kms_key_spec" {
  description = "AWS KMS key spec for OpenTofu state encryption"
  type        = string
  default     = "AES_256"
}

variable "display_name" {
  description = "Display name for the application registration"
  type        = string
}

variable "description" {
  description = "Description of the application"
  type        = string
  default     = null
}

variable "device_only_auth_enabled" {
  description = "Whether this application supports device-only authentication"
  type        = bool
  default     = null
}

variable "fallback_public_client_enabled" {
  description = "Whether the application is a public client fallback when no redirect URI matches"
  type        = bool
  default     = null
}

variable "group_membership_claims" {
  description = "Group claims emitted in tokens"
  type        = set(string)
  default     = null

  validation {
    condition = var.group_membership_claims == null || alltrue([
      for claim in var.group_membership_claims : contains(["All", "ApplicationGroup", "DirectoryRole", "None", "SecurityGroup"], claim)
    ])
    error_message = "group_membership_claims values must be one of All, ApplicationGroup, DirectoryRole, None, or SecurityGroup."
  }
}

variable "identifier_uris" {
  description = "User-defined URI identifiers for the application"
  type        = set(string)
  default     = null
}

variable "logo_image" {
  description = "Base64-encoded logo image in GIF, JPEG, or PNG format"
  type        = string
  default     = null
}

variable "marketing_url" {
  description = "URL of the application's marketing page"
  type        = string
  default     = null
}

variable "notes" {
  description = "Free text notes for the application"
  type        = string
  default     = null
}

variable "oauth2_post_response_required" {
  description = "Whether OAuth2 POST response is required"
  type        = bool
  default     = null
}

variable "owners" {
  description = "Object IDs of owners for the application"
  type        = set(string)
  default     = null
}

variable "prevent_duplicate_names" {
  description = "Return an error when another application has the same display name"
  type        = bool
  default     = null
}

variable "privacy_statement_url" {
  description = "URL of the application's privacy statement"
  type        = string
  default     = null
}

variable "service_management_reference" {
  description = "Service management reference for the application"
  type        = string
  default     = null
}

variable "sign_in_audience" {
  description = "Accounts that can sign in to the application"
  type        = string
  default     = "AzureADMyOrg"

  validation {
    condition     = contains(["AzureADMyOrg", "AzureADMultipleOrgs", "AzureADandPersonalMicrosoftAccount", "PersonalMicrosoftAccount"], var.sign_in_audience)
    error_message = "sign_in_audience must be a supported AzureAD audience value."
  }
}

variable "support_url" {
  description = "URL of the application's support page"
  type        = string
  default     = null
}

variable "tags" {
  description = "Application tags. Mutually exclusive with feature_tags"
  type        = set(string)
  default     = null
}

variable "template_id" {
  description = "Application template ID to instantiate"
  type        = string
  default     = null
}

variable "terms_of_service_url" {
  description = "URL of the application's terms of service"
  type        = string
  default     = null
}

variable "api" {
  description = "API permission and token settings exposed by this application"
  type = object({
    known_client_applications      = optional(set(string))
    mapped_claims_enabled          = optional(bool)
    requested_access_token_version = optional(number)
    oauth2_permission_scopes = optional(list(object({
      admin_consent_description  = string
      admin_consent_display_name = string
      enabled                    = optional(bool, true)
      id                         = string
      type                       = string
      user_consent_description   = optional(string)
      user_consent_display_name  = optional(string)
      value                      = optional(string)
    })), [])
  })
  default = null
}

variable "app_roles" {
  description = "Application roles exposed by this application"
  type = list(object({
    allowed_member_types = set(string)
    description          = string
    display_name         = string
    enabled              = optional(bool, true)
    id                   = string
    value                = optional(string)
  }))
  default = []
}

variable "feature_tags" {
  description = "Well-known feature tags for enterprise/gallery app behavior. Mutually exclusive with tags"
  type = object({
    custom_single_sign_on = optional(bool)
    enterprise            = optional(bool)
    gallery               = optional(bool)
    hide                  = optional(bool)
  })
  default = null
}

variable "optional_claims" {
  description = "Optional claims to include in access, ID, or SAML2 tokens"
  type = object({
    access_tokens = optional(list(object({
      additional_properties = optional(list(string))
      essential             = optional(bool)
      name                  = string
      source                = optional(string)
    })), [])
    id_tokens = optional(list(object({
      additional_properties = optional(list(string))
      essential             = optional(bool)
      name                  = string
      source                = optional(string)
    })), [])
    saml2_tokens = optional(list(object({
      additional_properties = optional(list(string))
      essential             = optional(bool)
      name                  = string
      source                = optional(string)
    })), [])
  })
  default = null
}

variable "password" {
  description = "Optional application password to create inline with the application"
  type = object({
    display_name = string
    end_date     = optional(string)
    start_date   = optional(string)
  })
  default = null
}

variable "public_client" {
  description = "Public client redirect URI settings"
  type = object({
    redirect_uris = optional(set(string))
  })
  default = null
}

variable "required_resource_access" {
  description = "Delegated permissions and app roles required from resource applications"
  type = list(object({
    resource_app_id = string
    resource_access = list(object({
      id   = string
      type = string
    }))
  }))
  default = []
}

variable "single_page_application" {
  description = "Single-page application redirect URI settings"
  type = object({
    redirect_uris = optional(set(string))
  })
  default = null
}

variable "web" {
  description = "Web application URLs, redirect URIs, and implicit grant settings"
  type = object({
    homepage_url  = optional(string)
    logout_url    = optional(string)
    redirect_uris = optional(set(string))
    implicit_grant = optional(object({
      access_token_issuance_enabled = optional(bool)
      id_token_issuance_enabled     = optional(bool)
    }))
  })
  default = null
}

variable "timeouts" {
  description = "Timeout configuration for application operations"
  type = object({
    create = optional(string)
    delete = optional(string)
    read   = optional(string)
    update = optional(string)
  })
  default = null
}

variable "aws_region" {
  type = string
}
variable "owner_object_id" {
  type = string
}
variable "owner_service_principal_name" {
  type = string
}
variable "credential_display_name" {
  type = string
}
variable "parameter_kms_key_id" {
  type = string
}
variable "parameter_tags" {
  type = map(string)
}
variable "sso_parameters" {
  type = map(object({
    description = string
    value_key   = string
  }))
  validation {
    condition = alltrue([
      for parameter in values(var.sso_parameters) :
      contains(["client_id", "client_secret", "tenant_id", "auth_url", "token_url", "issuer_url"], parameter.value_key)
    ])
    error_message = "SSO parameters must select a supported identity value."
  }
}
