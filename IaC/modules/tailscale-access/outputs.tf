output "github_identity_client_ids" {
  description = "Non-secret client IDs: publish plan/apply as environment TAILSCALE_CLIENT_ID; cordium as repository TAILSCALE_CORDIUM_CLIENT_ID."
  value       = { for name, identity in tailscale_federated_identity.github : name => identity.id }
}
