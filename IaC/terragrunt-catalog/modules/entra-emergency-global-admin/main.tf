data "azuread_domains" "tenant" {
  include_unverified = true
}

locals {
  tenant_initial_domains = [
    for domain in data.azuread_domains.tenant.domains : domain
    if try(domain["initial"], false)
  ]
  tenant_initial_domain      = try(one(local.tenant_initial_domains), null)
  tenant_initial_domain_name = try(local.tenant_initial_domain["domain_name"], "invalid.onmicrosoft.com")
  user_principal_name        = format("homelab-emergency-admin@%s", local.tenant_initial_domain_name)

  # Microsoft documents this built-in Global Administrator role template ID.
  global_administrator_role_template_id = "62e90394-69f5-4237-9190-012177145e10"
}

resource "random_password" "initial" {
  length           = 40
  min_lower        = 3
  min_upper        = 3
  min_numeric      = 3
  min_special      = 3
  override_special = "!@#%*-_+="
}

# A cloud-only recovery account is independent from the identity being converted.
resource "azuread_user" "this" {
  user_principal_name         = local.user_principal_name
  display_name                = "Homelab emergency administrator"
  mail_nickname               = "homelab-emergency-admin"
  account_enabled             = true
  password                    = random_password.initial.result
  force_password_change       = true
  disable_strong_password     = false
  disable_password_expiration = true

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [password, force_password_change]

    precondition {
      condition = (
        length(local.tenant_initial_domains) == 1 &&
        try(
          local.tenant_initial_domain["verified"] &&
          local.tenant_initial_domain["authentication_type"] == "Managed" &&
          endswith(local.tenant_initial_domain["domain_name"], ".onmicrosoft.com"),
          false,
        )
      )
      error_message = "Tenant must expose exactly one verified managed initial .onmicrosoft.com domain before creating the emergency administrator."
    }
  }
}

resource "azuread_directory_role_assignment" "global_administrator" {
  role_id             = local.global_administrator_role_template_id
  principal_object_id = azuread_user.this.object_id
  directory_scope_id  = "/"

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = endswith(azuread_user.this.user_principal_name, ".onmicrosoft.com")
      error_message = "The emergency Global Administrator must remain a cloud-only .onmicrosoft.com account."
    }
  }
}
