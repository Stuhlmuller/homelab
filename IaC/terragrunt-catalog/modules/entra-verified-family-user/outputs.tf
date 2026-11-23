output "user_principal_name" {
  description = "Pilot sign-in name for private credential handoff."
  value       = azuread_user.this.user_principal_name
  sensitive   = true
}

output "initial_password" {
  description = "One-time bootstrap password; privately hand off, then change interactively before PSSO registration."
  value       = random_password.initial.result
  sensitive   = true
}
