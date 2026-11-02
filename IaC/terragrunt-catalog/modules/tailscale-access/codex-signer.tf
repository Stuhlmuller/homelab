# A device reader and webhook do not distribute Tailnet Lock signing authority.
resource "tailscale_oauth_client" "codex_signer" {
  description = "Codex cloud signer device reader"
  scopes      = ["devices:core:read"]
}

resource "tailscale_webhook" "codex_signer" {
  endpoint_url = "https://codex-signer.tail67beb.ts.net/webhooks/tailscale"
  # Provider 0.29.2 lacks the nodeNeedsSignature enum. The receiver ignores all
  # other events in this category; this does not broaden its signing policy.
  subscriptions = ["categoryTailnetManagement"]
}

resource "tailscale_tailnet_key" "codex_signer" {
  description         = "Persistent homelab Codex signer enrollment"
  reusable            = false
  ephemeral           = false
  preauthorized       = true
  expiry              = 7776000
  recreate_if_invalid = "never"
  tags                = ["tag:codex-cloud-signer"]
  depends_on          = [tailscale_acl.homelab]
}

resource "tailscale_tailnet_key" "codex_cloud" {
  description         = "Codex cloud ephemeral agents"
  reusable            = true
  ephemeral           = true
  preauthorized       = true
  expiry              = 7776000
  recreate_if_invalid = "never"
  tags                = ["tag:codex-cloud"]
  depends_on          = [tailscale_acl.homelab]
}

locals {
  codex_signer_secrets = {
    "auth-key"            = tailscale_tailnet_key.codex_signer.key
    "oauth-client-id"     = tailscale_oauth_client.codex_signer.id
    "oauth-client-secret" = tailscale_oauth_client.codex_signer.key
    "webhook-secret"      = tailscale_webhook.codex_signer.secret
    "cloud-auth-key"      = tailscale_tailnet_key.codex_cloud.key
  }
}

resource "aws_ssm_parameter" "codex_signer" {
  for_each = toset(["auth-key", "oauth-client-id", "oauth-client-secret", "webhook-secret", "cloud-auth-key"])

  name        = "/homelab/tailscale/codex-cloud-signer/${each.key}"
  description = "Codex cloud signing service ${each.key}; managed by tailscale-access."
  type        = "SecureString"
  key_id      = "alias/aws/ssm"
  value       = local.codex_signer_secrets[each.key]

  lifecycle {
    prevent_destroy = true
  }
}
