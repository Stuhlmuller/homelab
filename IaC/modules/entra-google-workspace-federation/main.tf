terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.56.0"
    }
    msgraph = {
      source  = "microsoft/msgraph"
      version = "0.5.0"
    }
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
      condition = (
        self.output.verified == true &&
        self.output.authentication_type == "Managed" &&
        self.output.is_default == false &&
        self.output.is_initial == false
      )
      error_message = "The Google Workspace federation target must be a verified, managed, non-default, non-initial domain."
    }
  }
}

resource "msgraph_resource" "google_workspace" {
  url         = "domains/${var.domain_name}/federationConfiguration"
  api_version = "v1.0"
  body = {
    displayName                     = "Google Workspace Identity"
    issuerUri                       = local.metadata.issuer_uri
    activeSignInUri                 = local.metadata.sign_in_uri
    passiveSignInUri                = local.metadata.sign_in_uri
    signOutUri                      = "https://accounts.google.com/logout"
    signingCertificate              = local.metadata.signing_certificate
    preferredAuthenticationProtocol = "saml"
    federatedIdpMfaBehavior         = "acceptIfMfaDoneByFederatedIdp"
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition = (
        can(local.metadata.issuer_uri) &&
        can(local.metadata.sign_in_uri) &&
        can(local.metadata.signing_certificate) &&
        length(local.metadata.issuer_uri) > 0 &&
        length(local.metadata.sign_in_uri) > 0 &&
        length(local.metadata.signing_certificate) > 0
      )
      error_message = "The protected Google Workspace metadata parameter must contain issuer_uri, sign_in_uri, and signing_certificate."
    }
  }

  depends_on = [data.msgraph_resource.domain]
}
