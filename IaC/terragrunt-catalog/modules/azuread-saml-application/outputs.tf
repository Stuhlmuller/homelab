output "metadata_url" {
  description = "App-specific Entra federation metadata; feed privately to the service provider."
  value       = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/federationmetadata/2007-06/federationmetadata.xml?appid=${azuread_application.this.client_id}"
  sensitive   = true
  depends_on  = [msgraph_update_resource.signing_certificate]
}

output "tenant_id" {
  description = "Existing Entra tenant, for private runtime verification."
  value       = data.azuread_client_config.current.tenant_id
  sensitive   = true
}

output "client_id" {
  description = "Managed SAML application's client ID, for private runtime verification."
  value       = azuread_application.this.client_id
  sensitive   = true
}

output "service_principal_id" {
  description = "Enterprise application object ID, for private assignment and signing-key verification."
  value       = azuread_service_principal.this.object_id
  sensitive   = true
}

output "signing_certificate_expires_at" {
  description = "Expiry of the active Entra SAML signing certificate."
  value       = azuread_service_principal_token_signing_certificate.this.end_date
  sensitive   = true
}

output "signing_certificate_thumbprint" {
  description = "Active SAML signing certificate SHA-1 identifier, for private metadata verification."
  value       = azuread_service_principal_token_signing_certificate.this.thumbprint
  sensitive   = true
  depends_on  = [msgraph_update_resource.signing_certificate]
}
