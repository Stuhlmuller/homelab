output "id" {
  description = "The Terraform ID of the application"
  value       = azuread_application.this.id
}

output "object_id" {
  description = "The object ID of the application"
  value       = azuread_application.this.object_id
}

output "client_id" {
  description = "The client ID of the application"
  value       = azuread_application.this.client_id
}

output "display_name" {
  description = "The display name of the application"
  value       = azuread_application.this.display_name
}

output "app_role_ids" {
  description = "Mapping of app role values to generated app role IDs"
  value       = azuread_application.this.app_role_ids
}

output "oauth2_permission_scope_ids" {
  description = "Mapping of OAuth2 permission scope values to generated scope IDs"
  value       = azuread_application.this.oauth2_permission_scope_ids
}

output "publisher_domain" {
  description = "The verified publisher domain for the application"
  value       = azuread_application.this.publisher_domain
}

output "password" {
  description = "Inline application password metadata and value, when password is configured"
  value       = azuread_application.this.password
  sensitive   = true
}

output "sso_parameter_names" {
  value = keys(aws_ssm_parameter.sso)
}
output "sso_password_key_id" {
  value = azuread_application_password.sso.key_id
}
