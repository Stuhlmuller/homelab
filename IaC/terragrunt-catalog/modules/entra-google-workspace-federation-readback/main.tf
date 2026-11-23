# The bootstrap module is separate. Do not recreate or delete live federation here.
removed {
  from = msgraph_resource.google_workspace

  lifecycle {
    destroy = false
  }
}

data "aws_ssm_parameter" "google_workspace_metadata" {
  region          = var.aws_region
  name            = var.metadata_parameter_name
  with_decryption = true
}

locals {
  metadata = jsondecode(data.aws_ssm_parameter.google_workspace_metadata.value)
}

data "msgraph_resource" "domain" {
  url         = "domains/${var.domain_name}"
  api_version = "v1.0"

  response_export_values = {
    authentication_type = "authenticationType"
    is_default          = "isDefault"
    is_initial          = "isInitial"
    verified            = "isVerified"
  }

  lifecycle {
    postcondition {
      condition = try(
        self.output.verified == true &&
        self.output.authentication_type == "Federated" &&
        self.output.is_default == false &&
        self.output.is_initial == false,
        false
      )
      error_message = "Workspace federation readback requires a verified, federated, non-default, non-initial domain."
    }
  }
}

data "msgraph_resource" "federation" {
  url         = "domains/${var.domain_name}/federationConfiguration"
  api_version = "v1.0"

  response_export_values = {
    next_link           = "\"@odata.nextLink\""
    count               = "length(value)"
    federation_id       = "value[0].id"
    display_name        = "value[0].displayName"
    issuer_uri          = "value[0].issuerUri"
    active_sign_in_uri  = "value[0].activeSignInUri"
    passive_sign_in_uri = "value[0].passiveSignInUri"
    sign_out_uri        = "value[0].signOutUri"
    signing_certificate = "value[0].signingCertificate"
    protocol            = "value[0].preferredAuthenticationProtocol"
    mfa_behavior        = "value[0].federatedIdpMfaBehavior"
  }

  lifecycle {
    postcondition {
      condition = try(
        self.output.count == 1 &&
        try(self.output.next_link, null) == null &&
        length(trimspace(self.output.federation_id)) > 0 &&
        self.output.display_name == "Google Workspace Identity" &&
        length(trimspace(local.metadata.issuer_uri)) > 0 &&
        length(trimspace(local.metadata.sign_in_uri)) > 0 &&
        length(trimspace(local.metadata.signing_certificate)) > 0 &&
        self.output.issuer_uri == local.metadata.issuer_uri &&
        self.output.active_sign_in_uri == local.metadata.sign_in_uri &&
        self.output.passive_sign_in_uri == local.metadata.sign_in_uri &&
        self.output.sign_out_uri == "https://accounts.google.com/logout" &&
        sensitive(self.output.signing_certificate) == local.metadata.signing_certificate &&
        self.output.protocol == "saml" &&
        self.output.mfa_behavior == "acceptIfMfaDoneByFederatedIdp",
        false
      )
      error_message = "Workspace federation readback must match the single reviewed Google Workspace SAML configuration."
    }
  }
}
