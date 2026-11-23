mock_provider "msgraph" {}

variables {
  domain_name = "example.com"
}

run "verified_federated_domain" {
  command = plan

  override_data {
    target = data.msgraph_resource.domain
    values = {
      output = {
        verified            = true
        authentication_type = "Federated"
        is_default          = false
        is_initial          = false
      }
    }
  }

  assert {
    condition     = output.domain_status.authentication_type == "Federated"
    error_message = "The attestation must return the current federation mode."
  }
}

run "managed_domain_is_not_yet_federated" {
  command = plan

  override_data {
    target = data.msgraph_resource.domain
    values = {
      output = {
        verified            = true
        authentication_type = "Managed"
        is_default          = false
        is_initial          = false
      }
    }
  }

  expect_failures = [data.msgraph_resource.domain]
}

run "unverified_domain_is_rejected" {
  command = plan

  override_data {
    target = data.msgraph_resource.domain
    values = {
      output = {
        verified            = false
        authentication_type = "Federated"
        is_default          = false
        is_initial          = false
      }
    }
  }

  expect_failures = [data.msgraph_resource.domain]
}
