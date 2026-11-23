data "azuread_domains" "required" {
  count = var.required_verified_domain == null ? 0 : 1

  include_unverified = true
}

locals {
  required_domain = var.required_verified_domain == null ? null : one([
    for domain in data.azuread_domains.required[0].domains : domain
    if domain.domain_name == var.required_verified_domain
  ])
  user_principal_domain = lower(try(split("@", var.user_principal_name)[1], ""))
}

resource "random_password" "initial" {
  length           = 40
  min_lower        = 3
  min_upper        = 3
  min_numeric      = 3
  min_special      = 3
  override_special = "!@#%*-_+="
}

# Creating a regular user supplies an internal Entra credential. This is not an
# invitation, conversion of an existing identity, or a service-license grant.
resource "azuread_user" "this" {
  user_principal_name     = var.user_principal_name
  display_name            = var.display_name
  mail_nickname           = split("@", var.user_principal_name)[0]
  account_enabled         = true
  password                = random_password.initial.result
  force_password_change   = true
  disable_strong_password = false

  lifecycle {
    prevent_destroy = true
    # The user owns the permanent password after their first interactive login.
    ignore_changes = [password, force_password_change]

    precondition {
      condition = (
        var.required_verified_domain == null ||
        local.user_principal_domain == var.required_verified_domain
      )
      error_message = "required_verified_domain must exactly match the user_principal_name domain."
    }

    precondition {
      condition = var.required_verified_domain == null || try(
        local.required_domain["verified"] &&
        local.required_domain["authentication_type"] == "Managed" &&
        local.required_domain["default"] == false &&
        local.required_domain["initial"] == false,
        false
      )
      error_message = "required_verified_domain must be present, verified, managed, non-default and non-initial before creating the user."
    }
  }
}
