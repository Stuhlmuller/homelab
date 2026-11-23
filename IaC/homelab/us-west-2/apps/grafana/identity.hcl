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
    homepage_url = "https://grafana.stinkyboi.com"
    redirect_uris = [
      "https://grafana.stinkyboi.com/",
      "https://grafana.stinkyboi.com/login/azuread",
    ]
    implicit_grant = {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  tags = []

  owner_object_id              = "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
  owner_service_principal_name = "homelab-terraform-apply"
  credential_display_name      = "homelab-grafana-sso"
  sso_parameters = {
    "/homelab/grafana/azuread/client-id"             = { description = "Grafana Microsoft Entra OAuth client ID from the managed application registration.", value_key = "client_id" }
    "/homelab/grafana/azuread/client-secret"         = { description = "Grafana Microsoft Entra OAuth client secret from the managed application password.", value_key = "client_secret" }
    "/homelab/grafana/azuread/auth-url"              = { description = "Grafana Microsoft Entra OAuth authorization URL.", value_key = "auth_url" }
    "/homelab/grafana/azuread/token-url"             = { description = "Grafana Microsoft Entra OAuth token URL.", value_key = "token_url" }
    "/homelab/grafana/azuread/allowed-organizations" = { description = "Grafana allowed Microsoft Entra tenant ID.", value_key = "tenant_id" }
  }
}
