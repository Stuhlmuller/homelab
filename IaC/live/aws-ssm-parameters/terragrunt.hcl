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
    "/homelab/litellm/master-key" = {
      description   = "LiteLLM master key."
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
    "/homelab/openclaw/app-secret" = {
      description   = "OpenClaw application secret."
      initial_value = local.placeholder
    }
    "/homelab/openclaw/litellm-token" = {
      description   = "OpenClaw token for LiteLLM access."
      initial_value = local.placeholder
    }
    "/homelab/tines/app-secret" = {
      description   = "Tines application secret."
      initial_value = local.placeholder
    }
    "/homelab/tines/admin-password" = {
      description   = "Tines admin password."
      initial_value = local.placeholder
    }
  }
}
