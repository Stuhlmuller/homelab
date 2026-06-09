include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  app_url     = "https://stinkyboi.com"
  portal_url  = "https://portal.stinkyboi.com"
  aws_region  = local.root_config.locals.aws_region
  kms_key_id  = local.root_config.locals.kms_key_id
  tags = {
    for key, value in local.root_config.locals.default_tags :
    key => tostring(value)
  }
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/azuread-application?ref=19df2cb291eef0084cafb85bed644dcdb082108c"
}

dependencies {
  paths = [
    "../../aws-ssm-parameters",
  ]
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"
}
EOF
}

generate "azuread_provider" {
  path      = "azuread-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "azuread" {}
EOF
}

generate "sso_parameters" {
  path      = "sso-parameters.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
data "azuread_client_config" "current" {}

resource "azuread_application_password" "sso" {
  application_id    = azuread_application.this.id
  display_name      = "homelab-octelium-entra-oidc"
  end_date_relative = "8760h"
}

locals {
  octelium_entra_parameters = {
    "/homelab/octelium/entra/client-id" = {
      description = "Octelium Microsoft Entra OIDC client ID from the managed application registration."
      value       = azuread_application.this.client_id
    }
    "/homelab/octelium/entra/client-secret" = {
      description = "Octelium Microsoft Entra OIDC client secret from the managed application password."
      value       = azuread_application_password.sso.value
    }
    "/homelab/octelium/entra/issuer-url" = {
      description = "Octelium Microsoft Entra OIDC issuer URL."
      value       = format("https://login.microsoftonline.com/%s/v2.0", data.azuread_client_config.current.tenant_id)
    }
    "/homelab/octelium/entra/tenant-id" = {
      description = "Octelium Microsoft Entra tenant ID."
      value       = data.azuread_client_config.current.tenant_id
    }
  }
}

resource "aws_ssm_parameter" "sso" {
  for_each = local.octelium_entra_parameters

  region      = "${local.aws_region}"
  name        = each.key
  description = each.value.description
  type        = "SecureString"
  value       = each.value.value
  key_id      = "${local.kms_key_id}"
  tier        = "Standard"
  tags        = ${jsonencode(local.tags)}
}

output "sso_parameter_names" {
  description = "AWS SSM parameter names populated from the Octelium Microsoft Entra application."
  value       = keys(aws_ssm_parameter.sso)
}

output "sso_password_key_id" {
  description = "Key ID for the generated Octelium Microsoft Entra application password."
  value       = azuread_application_password.sso.key_id
}
EOF
}

inputs = {
  display_name            = "Octelium"
  prevent_duplicate_names = false
  sign_in_audience        = "AzureADMyOrg"

  required_resource_access = [
    {
      resource_app_id = "00000003-0000-0000-c000-000000000000"
      resource_access = [
        {
          id   = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"
          type = "Scope"
        },
        {
          id   = "37f7f235-527c-4136-accd-4a02d197296e"
          type = "Scope"
        },
        {
          id   = "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0"
          type = "Scope"
        },
        {
          id   = "14dad69e-099b-42c9-810b-d002981feec1"
          type = "Scope"
        },
        {
          id   = "7427e0e9-2fba-42fe-b0c0-848c9e6a8182"
          type = "Scope"
        },
      ]
    },
  ]

  web = {
    homepage_url = local.app_url
    redirect_uris = [
      "${local.app_url}/callback",
      "${local.portal_url}/callback",
    ]
    implicit_grant = {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  tags = []
}
