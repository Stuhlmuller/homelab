include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  app_url     = "https://grafana.stinkyboi.com"
  aws_region  = local.root_config.locals.aws_region
  kms_key_id  = local.root_config.locals.kms_key_id
  tags = {
    for key, value in local.root_config.locals.default_tags :
    key => tostring(value)
  }
}

terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/azuread-application?ref=0.4.0"
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
  display_name      = "homelab-grafana-sso"
  end_date_relative = "8760h"
}

locals {
  azuread_sso_parameters = {
    "/homelab/grafana/azuread/client-id" = {
      description = "Grafana Microsoft Entra OAuth client ID from the managed application registration."
      value       = azuread_application.this.client_id
    }
    "/homelab/grafana/azuread/client-secret" = {
      description = "Grafana Microsoft Entra OAuth client secret from the managed application password."
      value       = azuread_application_password.sso.value
    }
    "/homelab/grafana/azuread/auth-url" = {
      description = "Grafana Microsoft Entra OAuth authorization URL."
      value       = format("https://login.microsoftonline.com/%s/oauth2/v2.0/authorize", data.azuread_client_config.current.tenant_id)
    }
    "/homelab/grafana/azuread/token-url" = {
      description = "Grafana Microsoft Entra OAuth token URL."
      value       = format("https://login.microsoftonline.com/%s/oauth2/v2.0/token", data.azuread_client_config.current.tenant_id)
    }
    "/homelab/grafana/azuread/allowed-organizations" = {
      description = "Grafana allowed Microsoft Entra tenant ID."
      value       = data.azuread_client_config.current.tenant_id
    }
  }
}

resource "aws_ssm_parameter" "sso" {
  for_each = local.azuread_sso_parameters

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
  description = "AWS SSM parameter names populated from the Grafana Microsoft Entra application."
  value       = keys(aws_ssm_parameter.sso)
}

output "sso_password_key_id" {
  description = "Key ID for the generated Grafana Microsoft Entra application password."
  value       = azuread_application_password.sso.key_id
}
EOF
}

inputs = {
  display_name            = "Grafana"
  prevent_duplicate_names = false
  sign_in_audience        = "AzureADMyOrg"

  app_roles = [
    {
      allowed_member_types = [
        "User",
      ]
      description  = "Grafana administrators"
      display_name = "Grafana Administrators"
      enabled      = true
      id           = "7d1d19e8-d52a-4b83-b036-7abf1b8cfe34"
      value        = "GrafanaAdmin"
    },
    {
      allowed_member_types = [
        "User",
      ]
      description  = "Grafana editors"
      display_name = "Grafana Editors"
      enabled      = true
      id           = "145ece9f-9e3d-4d82-b94b-3ed072e57725"
      value        = "Editor"
    },
  ]

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
      "${local.app_url}/",
      "${local.app_url}/login/azuread",
    ]
    implicit_grant = {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  tags = []
}
