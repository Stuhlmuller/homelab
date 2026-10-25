output "github_identity_client_ids" {
  description = "Dormant OIDC identities retained until a separately reviewed retirement; do not publish these IDs."
  value       = { for name, identity in tailscale_federated_identity.github : name => identity.id }
}

output "github_auth_keys" {
  description = "Private input to tailscale-ci-configure.py only; never print or write to repository artifacts."
  sensitive   = true
  value = {
    for name, key in tailscale_tailnet_key.github : name => {
      id            = key.id
      key           = key.key
      expires_at    = key.expires_at
      generation    = var.ci_key_generation
      invalid       = key.invalid
      reusable      = key.reusable
      ephemeral     = key.ephemeral
      preauthorized = key.preauthorized
      tags          = key.tags
    }
  }
}
