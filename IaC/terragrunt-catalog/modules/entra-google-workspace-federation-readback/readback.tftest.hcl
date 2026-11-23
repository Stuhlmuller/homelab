mock_provider "aws" {
  mock_data "aws_ssm_parameter" {
    defaults = {
      value = <<-JSON
        {"issuer_uri":"https://issuer.example","sign_in_uri":"https://signin.example","signing_certificate":"fixture-certificate"}
      JSON
    }
  }
}

mock_provider "msgraph" {}

variables {
  aws_region              = "us-west-2"
  domain_name             = "homelab.example"
  metadata_parameter_name = "/homelab/test/workspace-federation"
}

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

override_data {
  target = data.msgraph_resource.federation
  values = {
    output = {
      count               = 1
      federation_id       = "fixture-id"
      display_name        = "Google Workspace Identity"
      issuer_uri          = "https://issuer.example"
      active_sign_in_uri  = "https://signin.example"
      passive_sign_in_uri = "https://signin.example"
      sign_out_uri        = "https://accounts.google.com/logout"
      signing_certificate = "fixture-certificate"
      protocol            = "saml"
      mfa_behavior        = "acceptIfMfaDoneByFederatedIdp"
    }
  }
}

run "exact_federation_without_managed_state" {
  command = plan

  assert {
    condition     = output.domain_name == "homelab.example"
    error_message = "The read-only unit must preserve the domain output."
  }
}

run "managed_domain_requires_bootstrap" {
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

run "multiple_federation_records_fail" {
  command = plan

  override_data {
    target = data.msgraph_resource.federation
    values = {
      output = {
        count               = 2
        federation_id       = "fixture-id"
        display_name        = "Google Workspace Identity"
        issuer_uri          = "https://issuer.example"
        active_sign_in_uri  = "https://signin.example"
        passive_sign_in_uri = "https://signin.example"
        sign_out_uri        = "https://accounts.google.com/logout"
        signing_certificate = "fixture-certificate"
        protocol            = "saml"
        mfa_behavior        = "acceptIfMfaDoneByFederatedIdp"
      }
    }
  }

  expect_failures = [data.msgraph_resource.federation]
}

run "unexpected_federation_mfa_fails" {
  command = plan

  override_data {
    target = data.msgraph_resource.federation
    values = {
      output = {
        count               = 1
        federation_id       = "fixture-id"
        display_name        = "Google Workspace Identity"
        issuer_uri          = "https://issuer.example"
        active_sign_in_uri  = "https://signin.example"
        passive_sign_in_uri = "https://signin.example"
        sign_out_uri        = "https://accounts.google.com/logout"
        signing_certificate = "fixture-certificate"
        protocol            = "saml"
        mfa_behavior        = "rejectMfaByFederatedIdp"
      }
    }
  }

  expect_failures = [data.msgraph_resource.federation]
}
