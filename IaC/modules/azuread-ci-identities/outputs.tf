output "tenant_id" {
  description = "Directory ID for the protected GitHub environment authentication settings."
  value       = data.azuread_client_config.current.tenant_id
  sensitive   = true
}

output "client_ids" {
  description = "Application client IDs keyed by plan/apply; publish only to the corresponding protected environment."
  value       = { for identity, application in azuread_application.ci : identity => application.client_id }
  sensitive   = true
}

output "service_principal_ids" {
  description = "Service principal object IDs for explicit managed-application ownership."
  value       = { for identity, principal in azuread_service_principal.ci : identity => principal.object_id }
  sensitive   = true
}
