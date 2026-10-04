data "azuread_client_config" "current" {}

data "azuread_user" "operator" {
  user_principal_name = var.operator_user_principal_name
}

data "azuread_service_principal" "microsoft_graph" {
  client_id = "00000003-0000-0000-c000-000000000000"
}

locals {
  # These are deliberately fixed: widening trust or permissions needs a code review.
  read_permissions = toset([
    "Application.Read.All",
    "User.Read.All",
    "Policy.Read.All",
  ])
  identities = {
    plan = {
      display_name = "homelab-terraform-plan"
      environment  = "homelab-plan"
      permissions  = local.read_permissions
    }
    apply = {
      display_name = "homelab-terraform-apply"
      environment  = "homelab-production"
      permissions  = setunion(local.read_permissions, ["Application.ReadWrite.OwnedBy"])
    }
  }
  permission_grants = merge([
    for identity, config in local.identities : {
      for permission in config.permissions : "${identity}/${permission}" => {
        identity   = identity
        permission = permission
      }
    }
  ]...)
}

resource "azuread_application" "ci" {
  for_each = local.identities

  display_name            = each.value.display_name
  description             = "Operator-managed ${each.key} identity for Stuhlmuller/homelab GitHub Actions."
  sign_in_audience        = "AzureADMyOrg"
  prevent_duplicate_names = true
  owners                  = [data.azuread_user.operator.object_id]

  required_resource_access {
    resource_app_id = data.azuread_service_principal.microsoft_graph.client_id

    dynamic "resource_access" {
      for_each = each.value.permissions
      content {
        id   = data.azuread_service_principal.microsoft_graph.app_role_ids[resource_access.value]
        type = "Role"
      }
    }
  }

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = data.azuread_client_config.current.object_id == data.azuread_user.operator.object_id
      error_message = "Manage CI identities only with the declared human operator session, never a CI service principal."
    }
  }
}

resource "azuread_service_principal" "ci" {
  for_each = local.identities

  client_id = azuread_application.ci[each.key].client_id
  owners    = [data.azuread_user.operator.object_id]

  lifecycle {
    prevent_destroy = true
  }
}

resource "azuread_application_federated_identity_credential" "github" {
  for_each = local.identities

  application_id = azuread_application.ci[each.key].id
  display_name   = each.value.environment
  description    = "Only the protected ${each.value.environment} environment in Stuhlmuller/homelab."
  issuer         = "https://token.actions.githubusercontent.com"
  audiences      = ["api://AzureADTokenExchange"]
  subject        = "repo:Stuhlmuller/homelab:environment:${each.value.environment}"
}

# required_resource_access requests permissions; these assignments grant them.
# CI cannot manage this unit or its own grants with the permissions above.
resource "azuread_app_role_assignment" "microsoft_graph" {
  for_each = local.permission_grants

  app_role_id         = data.azuread_service_principal.microsoft_graph.app_role_ids[each.value.permission]
  principal_object_id = azuread_service_principal.ci[each.value.identity].object_id
  resource_object_id  = data.azuread_service_principal.microsoft_graph.object_id
}
