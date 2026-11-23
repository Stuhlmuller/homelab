mock_provider "azuread" {
  mock_data "azuread_domains" {
    defaults = {
      domains = [{
        domain_name         = "example.net"
        verified            = true
        authentication_type = "Federated"
        default             = false
        initial             = false
        admin_managed       = true
        root                = true
        supported_services  = []
      }]
    }
  }

  mock_data "azuread_user" {
    defaults = {
      user_principal_name     = "pilot@example.net"
      account_enabled         = true
      user_type               = "Member"
      onpremises_sync_enabled = false
    }
  }
}

variables {
  pilot_object_id          = "00000000-0000-0000-0000-000000000001"
  user_principal_name      = "pilot@example.net"
  required_verified_domain = "example.net"
}

run "attests_existing_pilot_without_managed_state" {
  command = plan

  assert {
    condition     = nonsensitive(output.user_principal_name) == "pilot@example.net"
    error_message = "The state-empty plan must attest the existing pilot."
  }
}

run "rejects_non_federated_domain" {
  command = plan

  override_data {
    target = data.azuread_domains.required
    values = {
      domains = [{
        domain_name         = "example.net"
        verified            = true
        authentication_type = "Managed"
        default             = false
        initial             = false
        admin_managed       = true
        root                = true
        supported_services  = []
      }]
    }
  }

  expect_failures = [data.azuread_user.pilot]
}

run "rejects_unexpected_pilot_upn" {
  command = plan

  override_data {
    target = data.azuread_user.pilot
    values = {
      user_principal_name = "different@example.net"
    }
  }

  expect_failures = [data.azuread_user.pilot]
}
