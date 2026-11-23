data "azuread_domains" "required" {
  include_unverified = true
}

locals {
  required_domain = one([
    for domain in data.azuread_domains.required.domains : domain
    if domain.domain_name == var.required_verified_domain
  ])
}

data "azuread_user" "pilot" {
  object_id = var.pilot_object_id

  lifecycle {
    precondition {
      condition = try(
        endswith(var.user_principal_name, "@${var.required_verified_domain}") &&
        local.required_domain.verified &&
        local.required_domain.authentication_type == "Federated" &&
        !local.required_domain.default &&
        !local.required_domain.initial,
        false
      )
      error_message = "The retained pilot requires the verified, non-default and non-initial Federated domain."
    }

    postcondition {
      condition = (
        self.object_id == var.pilot_object_id &&
        self.user_principal_name == var.user_principal_name &&
        self.account_enabled &&
        self.user_type == "Member" &&
        self.onpremises_sync_enabled != true
      )
      error_message = "The registered object must remain the existing enabled cloud-only pilot Member with the exact UPN."
    }
  }
}

# Retire the old state bindings without deleting the live account or resetting its password.
removed {
  from = azuread_user.this

  lifecycle {
    destroy = false
  }
}

removed {
  from = random_password.initial

  lifecycle {
    destroy = false
  }
}

output "user_principal_name" {
  description = "The attested pilot identity."
  value       = data.azuread_user.pilot.user_principal_name
  sensitive   = true
}
