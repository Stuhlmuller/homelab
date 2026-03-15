resource "aws_ssm_parameter" "anthropic_api_key" {
  #checkov:skip=CKV_AWS_337: Need to update with project key
  name        = "/homelab/${kubernetes_namespace_v1.openclaw_operator.metadata[0].name}/anthropic_api_key"
  description = "Anthropic API key for OpenClaw operator"
  type        = "SecureString"
  value       = "update_me"
  lifecycle {
    ignore_changes = [value]
  }
}

resource "kubernetes_manifest" "openclaw_api_keys_secret" {
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"
    metadata = {
      name      = "openclaw-api-keys"
      namespace = kubernetes_namespace_v1.openclaw_operator.metadata[0].name
    }
    spec = {
      secretStoreRef = {
        name = "parameterstore"
        kind = "ClusterSecretStore"
      }
      refreshPolicy = "OnChange"
      target = {
        name = "openclaw-api-keys"
      }
      data = [{
        secretKey = "ANTHROPIC_API_KEY"
        remoteRef = {
          key = aws_ssm_parameter.anthropic_api_key.name
        }
      }]
    }
  }
}
