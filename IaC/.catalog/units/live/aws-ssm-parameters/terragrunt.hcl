include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  root_config        = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  aws_region         = local.root_config.locals.aws_region
  placeholder        = "REPLACE_ME"
  argocd_oidc_issuer = "https://login.microsoftonline.com/2aee152b-5281-40d0-8f4b-60faf40514ab/v2.0"
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
  create_kms_key = false
  kms_key_id     = local.root_config.locals.runtime_kms_key_id
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
    "/homelab/harbor/admin-password" = {
      description = "Initial Harbor administrator password."
      generated = {
        length  = 32
        special = false
        prefix  = "Aa1"
      }
    }
    "/homelab/harbor/secret-key" = {
      description = "Harbor database credential encryption key; retain with database backups."
      generated = {
        length  = 16
        special = false
      }
    }
    "/homelab/harbor/core-secret" = {
      description = "Harbor core service authentication secret."
      generated = {
        length  = 16
        special = false
      }
    }
    "/homelab/harbor/xsrf-key" = {
      description = "Harbor core CSRF signing key."
      generated = {
        length  = 32
        special = false
      }
    }
    "/homelab/harbor/jobservice-secret" = {
      description = "Harbor jobservice authentication secret."
      generated = {
        length  = 16
        special = false
      }
    }
    "/homelab/harbor/registry-http-secret" = {
      description = "Harbor registry upload signing secret."
      generated = {
        length  = 16
        special = false
      }
    }
    "/homelab/harbor/registry-password" = {
      description = "Harbor internal registry controller credential."
      generated = {
        length  = 32
        special = false
      }
    }
    "/homelab/harbor/database-password" = {
      description = "Harbor dedicated PostgreSQL password."
      generated = {
        length  = 32
        special = false
      }
    }
    "/homelab/harbor/robot-pull-password" = {
      description = "Harbor homelab project read-only robot credential."
      generated = {
        length  = 32
        special = false
        prefix  = "Aa1"
      }
    }
    "/homelab/harbor/robot-push-password" = {
      description = "Harbor homelab project publisher robot credential."
      generated = {
        length  = 32
        special = false
        prefix  = "Aa1"
      }
    }
    "/homelab/nofx/harbor-pull-password" = {
      description = "Namespace-scoped copy of the read-only Harbor homelab project robot credential."
      generated = {
        source_parameter = "/homelab/harbor/robot-pull-password"
      }
    }
    "/homelab/argocd/oidc/issuer" = {
      description   = "Argo CD OIDC issuer URL used for provider discovery."
      initial_value = local.argocd_oidc_issuer
    }
    "/homelab/argocd/oidc/client-id" = {
      description   = "Argo CD OIDC client ID issued by the IdP."
      initial_value = local.placeholder
    }
    "/homelab/argocd/oidc/client-secret" = {
      description   = "Argo CD OIDC client secret."
      initial_value = local.placeholder
    }
    "/homelab/argocd-image-updater/github-app/id" = {
      description   = "Retired Image Updater GitHub App ID retained as an IaC state tombstone; no workload consumes it."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/argocd-image-updater/github-app/installation-id" = {
      description   = "Retired Image Updater GitHub App installation ID retained as an IaC state tombstone; no workload consumes it."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/argocd-image-updater/github-app/private-key" = {
      description   = "Retired Image Updater GitHub App private key retained as an IaC state tombstone; no workload consumes it."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/affine/postgres-password" = {
      description = "AFFiNE dedicated PostgreSQL application password."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/affine/redis-password" = {
      description = "AFFiNE dedicated Redis authentication password."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/affine/private-key" = {
      description = "AFFiNE P-256 ECDSA private key used for signing tokens and encrypting application data."
      generated = {
        kind = "ecdsa_private_key"
      }
      initial_value = local.placeholder
    }
    "/homelab/cert-manager/cloudflare-api-token" = {
      description   = "Cloudflare API token used by cert-manager for DNS-01 challenges."
      initial_value = local.placeholder
    }
    "/homelab/cordium/agent-auth-token" = {
      description   = "Octelium authentication token used to apply the Cordium ClusterConfig."
      initial_value = local.placeholder
    }
    "/homelab/external-secrets/aws-ssm/access-key-id" = {
      description   = "AWS access key ID used by External Secrets to read homelab SSM parameters."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/external-secrets/aws-ssm/secret-access-key" = {
      description   = "AWS secret access key used by External Secrets to read homelab SSM parameters."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/github-actions-runner/registration-token" = {
      description   = "Retired GitHub Actions runner token retained as an IaC state tombstone; no workload consumes it."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/tailscale/oauth-client-id" = {
      description   = "Tailscale Kubernetes operator OAuth client ID."
      initial_value = local.placeholder
    }
    "/homelab/tailscale/oauth-client-secret" = {
      description   = "Tailscale Kubernetes operator OAuth client secret."
      initial_value = local.placeholder
    }
    "/homelab/octelium/client-auth-token" = {
      description   = "Octelium authentication token for the homelab workload client connector."
      initial_value = local.placeholder
    }
    "/homelab/octelium/cloudflare-tunnel-credentials-json" = {
      description   = "Cloudflare Tunnel credentials JSON for the public Octelium control-plane connector."
      initial_value = local.placeholder
    }
    "/homelab/octelium/cloudflare-tunnel-id" = {
      description   = "Cloudflare Tunnel UUID for the public Octelium control-plane connector."
      initial_value = local.placeholder
    }
    "/homelab/octelium/cloudflare-zone-settings-token" = {
      description   = "Legacy Cloudflare zone-settings token placeholder with no runtime consumer; retained pending separate retirement review."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/octelium/postgres-password" = {
      description = "Octelium Cluster PostgreSQL password."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/octelium/redis-password" = {
      description = "Octelium Cluster Redis password."
      generated = {
        length  = 40
        special = false
      }
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
    "/homelab/grafana/openclaw-alert-hook-token" = {
      description = "Shared bearer token used by Grafana to send alert webhooks directly to OpenClaw hooks."
      generated = {
        length  = 64
        special = false
      }
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
      reader_access = false
    }
    "/homelab/deluge/vpn/wireguard-config" = {
      description   = "Deluge AirVPN WireGuard wg0.conf profile."
      initial_value = local.placeholder
    }
    "/homelab/deluge/vpn/wireguard-preshared-key" = {
      description   = "Deluge AirVPN WireGuard pre-shared key."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/deluge/vpn/wireguard-public-key" = {
      description   = "Deluge AirVPN WireGuard peer public key from the selected profile."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/deluge/vpn/wireguard-addresses" = {
      description   = "Deluge AirVPN WireGuard interface address CIDR."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/deluge/vpn/wireguard-endpoint-ip" = {
      description   = "Deluge AirVPN WireGuard endpoint IP from the selected profile."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/deluge/vpn/wireguard-endpoint-port" = {
      description   = "Deluge AirVPN WireGuard endpoint port from the selected profile."
      initial_value = local.placeholder
      reader_access = false
    }
    "/homelab/media-postgres/app-password" = {
      description = "Shared PostgreSQL password for Sonarr, Radarr, and Prowlarr."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/media-postgres/dispatcharr-app-password" = {
      description = "Dedicated PostgreSQL password for Dispatcharr."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/nofx/ghcr-read-token" = {
      description   = "Dedicated classic GitHub PAT with read:packages only for private NOFX image pulls."
      initial_value = local.placeholder
    }
    "/homelab/nofx/jwt-secret" = {
      description = "NOFX JWT signing secret."
      generated = {
        length  = 64
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/nofx/data-encryption-key" = {
      description = "NOFX data encryption key for encrypted application secrets."
      generated = {
        length  = 44
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/nofx/rsa-private-key" = {
      description = "NOFX RSA private key used for browser-to-server transport encryption."
      generated = {
        kind = "rsa_private_key"
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
    "/homelab/openclaw/discord-bot-token" = {
      description   = "OpenClaw Discord bot token used to configure the Discord channel account at startup."
      initial_value = local.placeholder
    }
    "/homelab/openclaw/grafana/username" = {
      description   = "Grafana username for Claw to inspect homelab dashboards and alerts."
      initial_value = local.placeholder
    }
    "/homelab/openclaw/grafana/password" = {
      description   = "Grafana password for Claw to inspect homelab dashboards and alerts."
      initial_value = local.placeholder
    }
    "/homelab/openclaw/github-app/id" = {
      description   = "OpenClaw GitHub App ID."
      initial_value = local.placeholder
    }
    "/homelab/openclaw/github-app/installation-id" = {
      description   = "OpenClaw GitHub App installation ID."
      initial_value = local.placeholder
    }
    "/homelab/openclaw/github-app/private-key" = {
      description   = "OpenClaw GitHub App private key PEM."
      initial_value = local.placeholder
    }
    "/homelab/multica/dev-verification-code" = {
      description = "Multica fixed email verification code; access remains gated by Octelium."
      generated = {
        length  = 6
        lower   = false
        special = false
        upper   = false
      }
    }
    "/homelab/multica/jwt-secret" = {
      description = "Multica JWT signing secret."
      generated = {
        length  = 64
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/multica/postgres-password" = {
      description = "Multica dedicated PostgreSQL password."
      generated = {
        length  = 40
        special = false
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
    "/homelab/n8n/postgres-admin-password" = {
      description = "n8n dedicated PostgreSQL admin password."
      generated = {
        length  = 40
        special = false
      }
      initial_value = local.placeholder
    }
    "/homelab/n8n/postgres-app-password" = {
      description = "n8n dedicated PostgreSQL application user password."
      generated = {
        length  = 40
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
  }
}
