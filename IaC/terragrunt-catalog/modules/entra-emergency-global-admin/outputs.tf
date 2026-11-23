output "user_principal_name" {
  description = "Private sign-in name for the emergency administrator."
  value       = azuread_user.this.user_principal_name
  sensitive   = true
}

output "initial_password" {
  description = "One-time bootstrap password; privately hand off and replace at first sign-in."
  value       = random_password.initial.result
  sensitive   = true
}
