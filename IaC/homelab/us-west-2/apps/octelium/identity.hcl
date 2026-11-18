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
    homepage_url = "https://stinkyboi.com"
    redirect_uris = [
      "https://stinkyboi.com/callback",
      "https://portal.stinkyboi.com/callback",
    ]
    implicit_grant = {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  tags = []

  owner_object_id              = "08dfba7f-71ea-4eae-ae56-b3fb6cb2ad45"
  owner_service_principal_name = "homelab-terraform-apply"
  credential_display_name      = "homelab-octelium-entra-oidc"
  sso_parameters = {
    "/homelab/octelium/entra/client-id"     = { description = "Octelium Microsoft Entra OIDC client ID from the managed application registration.", value_key = "client_id" }
    "/homelab/octelium/entra/client-secret" = { description = "Octelium Microsoft Entra OIDC client secret from the managed application password.", value_key = "client_secret" }
    "/homelab/octelium/entra/issuer-url"    = { description = "Octelium Microsoft Entra OIDC issuer URL.", value_key = "issuer_url" }
    "/homelab/octelium/entra/tenant-id"     = { description = "Octelium Microsoft Entra tenant ID.", value_key = "tenant_id" }
  }
}
