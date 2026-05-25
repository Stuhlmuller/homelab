# AWS SSM Secret References

External Secrets uses AWS SSM Parameter Store for runtime secret material. This
repository may commit parameter names and Kubernetes Secret target names, but it
must not commit secret values.

## Placeholder Rules

- Parameter paths use the copyable public prefix `/homelab/<app>/<name>`.
- Values live only in AWS SSM Parameter Store or another approved runtime
  secret injection path.
- Placeholder manifests must identify the expected runtime secret and purpose.
- Provider credentials for External Secrets itself are copied into Kubernetes by
  the Terragrunt stack at
  `IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth`. The stack reads
  encrypted SSM parameters and creates only the `external-secrets/aws-ssm-auth`
  Kubernetes Secret through the Kubernetes provider.

## Secret Reference Matrix

The Parameter Store entries in this table are managed by Terragrunt at
`IaC/live/aws-ssm-parameters`. Terragrunt creates each value as a
`SecureString` placeholder and ignores later value changes so operators can
replace `REPLACE_ME` directly in AWS without committing secret material.

## External Secrets AWS Auth Bootstrap

External Secrets cannot read Parameter Store until the cluster has the
`external-secrets/aws-ssm-auth` Kubernetes Secret. This repository creates that
Secret through the Kubernetes Terraform provider in
`IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth`.

Bootstrap order:

1. Apply `IaC/live/aws-ssm-parameters` to create the SSM placeholders.
2. Replace `/homelab/external-secrets/aws-ssm/access-key-id` and
   `/homelab/external-secrets/aws-ssm/secret-access-key` with an IAM access key
   that can read `/homelab/*` Parameter Store values and decrypt the configured
   KMS key.
3. Apply `IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth`.

The Kubernetes Secret stack refuses to apply while either SSM value is empty or
still set to `REPLACE_ME`. The decrypted credential values are not committed to
git, but they are copied into the encrypted OpenTofu remote state for that
stack because Terraform manages the Kubernetes Secret.

| App | ExternalSecret | Target Secret | SSM parameters |
|-----|----------------|---------------|----------------|
| argocd | `argocd-oidc-sso` | `argocd-oidc-sso` | `/homelab/argocd/oidc/url`, `/homelab/argocd/oidc/issuer`, `/homelab/argocd/oidc/client-id`, `/homelab/argocd/oidc/client-secret` |
| cert-manager | `cert-manager-cloudflare-api-token` | `cloudflare-api-token` | `/homelab/cert-manager/cloudflare-api-token` |
| external-secrets | Terragrunt-managed Kubernetes provider Secret | `aws-ssm-auth` | `/homelab/external-secrets/aws-ssm/access-key-id`, `/homelab/external-secrets/aws-ssm/secret-access-key` |
| tailscale | `tailscale-oauth` | `operator-oauth` | `/homelab/tailscale/oauth-client-id`, `/homelab/tailscale/oauth-client-secret` |
| grafana | `grafana-admin` | `grafana-admin` | `/homelab/grafana/admin-user`, `/homelab/grafana/admin-password` |
| litellm | `litellm-provider-keys` | `litellm-provider-keys` | `/homelab/litellm/master-key`, `/homelab/litellm/openai-api-key` |
| openclaw | `openclaw-secrets` | `openclaw-secrets` | `/homelab/openclaw/app-secret`, `/homelab/openclaw/litellm-token` |
| tines | `tines-secrets` | `tines-secrets` | `/homelab/tines/app-secret`, `/homelab/tines/admin-password` |

The cert-manager Cloudflare value should be a scoped API token with permission
to read the zone and edit DNS records for `stinkyboi.com`; do not store the
token itself in git.

Deluge, Radarr, and Sonarr do not store their application passwords or API keys
in SSM. Their configuration lives on the persistent `/config` volumes and is
managed through each app after first login.
