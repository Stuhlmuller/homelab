include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  aws_region  = local.root_config.locals.aws_region
  placeholder = "REPLACE_ME"
}

terraform {
  source = "../../modules/aws-ssm-parameters"
}

generate "aws_provider" {
  path      = "aws-provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"
}
EOF
}

inputs = {
  aws_region     = local.aws_region
  create_kms_key = true
  parameter_reader_iam_user_names = [
    "external-secrets_aws-ssm-auth",
  ]
  additional_parameter_reader_names = [
    "/homelab/grafana/azuread/client-id",
    "/homelab/grafana/azuread/client-secret",
    "/homelab/grafana/azuread/auth-url",
    "/homelab/grafana/azuread/token-url",
    "/homelab/grafana/azuread/allowed-organizations",
  ]

  parameters = {
    "/homelab/argocd/oidc/issuer" = {
      description   = "Argo CD OIDC issuer URL used for provider discovery."
      initial_value = local.placeholder
    }
    "/homelab/argocd/oidc/client-id" = {
      description   = "Argo CD OIDC client ID issued by the IdP."
      initial_value = local.placeholder
    }
    "/homelab/argocd/oidc/client-secret" = {
      description   = "Argo CD OIDC client secret."
      initial_value = local.placeholder
    }
    "/homelab/cert-manager/cloudflare-api-token" = {
      description   = "Cloudflare API token used by cert-manager for DNS-01 challenges."
      initial_value = local.placeholder
    }
    "/homelab/external-secrets/aws-ssm/access-key-id" = {
      description   = "AWS access key ID used by External Secrets to read homelab SSM parameters."
      initial_value = local.placeholder
    }
    "/homelab/external-secrets/aws-ssm/secret-access-key" = {
      description   = "AWS secret access key used by External Secrets to read homelab SSM parameters."
      initial_value = local.placeholder
    }
    "/homelab/tailscale/oauth-client-id" = {
      description   = "Tailscale Kubernetes operator OAuth client ID."
      initial_value = local.placeholder
    }
    "/homelab/tailscale/oauth-client-secret" = {
      description   = "Tailscale Kubernetes operator OAuth client secret."
      initial_value = local.placeholder
    }
    "/homelab/grafana/admin-user" = {
      description   = "Grafana admin username."
      initial_value = local.placeholder
    }
    "/homelab/grafana/admin-password" = {
      description   = "Grafana admin password."
      initial_value = local.placeholder
    }
    "/homelab/grafana/discord-webhook-url" = {
      description   = "Discord incoming webhook URL used by Grafana alert notifications."
      initial_value = local.placeholder
    }
    "/homelab/litellm/master-key" = {
      description = "LiteLLM master key."
      generated = {
        length  = 48
        prefix  = "sk-"
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/litellm/openai-api-key" = {
      description   = "LiteLLM OpenAI provider API key."
      initial_value = local.placeholder
    }
    "/homelab/deluge/vpn/wireguard-private-key" = {
      description   = "Deluge AirVPN WireGuard private key."
      initial_value = local.placeholder
    }
    "/homelab/deluge/vpn/wireguard-preshared-key" = {
      description   = "Deluge AirVPN WireGuard pre-shared key."
      initial_value = local.placeholder
    }
    "/homelab/deluge/vpn/wireguard-addresses" = {
      description   = "Deluge AirVPN WireGuard interface address CIDR."
      initial_value = local.placeholder
    }
    "/homelab/media-postgres/app-password" = {
      description = "Shared PostgreSQL password for Sonarr, Radarr, and Prowlarr."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/openclaw/app-secret" = {
      description = "OpenClaw application secret."
      generated = {
        length  = 64
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/openclaw/litellm-token" = {
      description = "OpenClaw token for LiteLLM access."
      generated = {
        source_parameter = "/homelab/litellm/master-key"
      }
      initial_value = local.placeholder
    }
    "/homelab/n8n/encryption-key" = {
      description = "n8n instance encryption key for saved credentials and encrypted data."
      generated = {
        length  = 64
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/policy-bot/github-app/integration-id" = {
      description   = "Policy Bot GitHub App integration ID."
      initial_value = local.placeholder
    }
    "/homelab/policy-bot/github-app/webhook-secret" = {
      description = "Policy Bot GitHub App webhook HMAC secret."
      generated = {
        length  = 64
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/policy-bot/github-app/private-key" = {
      description   = "Policy Bot GitHub App private key PEM."
      initial_value = local.placeholder
    }
    "/homelab/policy-bot/oauth/client-id" = {
      description   = "Policy Bot GitHub App OAuth client ID."
      initial_value = local.placeholder
    }
    "/homelab/policy-bot/oauth/client-secret" = {
      description   = "Policy Bot GitHub App OAuth client secret."
      initial_value = local.placeholder
    }
    "/homelab/policy-bot/sessions-key" = {
      description = "Policy Bot session cookie signing key."
      generated = {
        length  = 64
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/hummingbot/config-password" = {
      description = "Hummingbot client password used to encrypt local bot credentials."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
  }
}
