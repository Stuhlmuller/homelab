# Secrets And Identity

Tags: #architecture #secrets #identity

## Boundary

This public repo may commit secret references, ExternalSecret names, SSM
parameter paths, non-secret defaults, encrypted material, and templates. It must
not commit secret values, kubeconfigs with private credentials, Talos secrets,
raw certificates, tokens, private SSH keys, or private keys.

Runtime app secrets are pulled from AWS SSM Parameter Store by External
Secrets. External Secrets itself uses a Kubernetes Secret created through the
`IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth` Terragrunt stack
after placeholder SSM parameters exist and real credential values are injected
outside git.

The SSM SecureString key is managed by `IaC/live/aws-ssm-parameters` in
`us-west-2` under `alias/homelab-opentofu`. It is distinct from the
OpenTofu remote-state key with the same alias in `us-east-1`; production apply
roles need identity-based KMS permissions for both keys.

## AWS SSM Pattern

- Public parameter prefix: `/homelab/<app>/<name>`
- Region: `us-west-2`
- Runtime secret values live outside git.
- ExternalSecret namespace access is constrained by the `aws-ssm`
  ClusterSecretStore namespace allow-list.
- Add a namespace to that allow-list in the same change that adds its first
  ExternalSecret.

## Identity Notes

- Argo CD SSO uses the `argocd-oidc-sso` ExternalSecret for the upstream OIDC
  issuer compatibility copy, client ID, and client secret. Dex startup uses the
  literal Microsoft Entra issuer committed in
  `IaC/bootstrap/argocd/terragrunt.hcl` so a placeholder SSM value cannot stop
  provider discovery. Microsoft Entra group authorization is a token-claim
  behavior, not a requested OAuth scope: keep Dex scopes to `openid`,
  `profile`, and `email`, configure Entra to emit the `groups` claim for Argo
  CD RBAC, and keep `insecureSkipEmailVerified: true` because Entra may omit
  the `email_verified` claim.
- Argo CD Image Updater uses the `argocd-image-updater-git` ExternalSecret for
  GitHub App credentials that open image update pull requests through Git
  write-back. It refreshes on ExternalSecret changes; bump the non-secret
  `homelab.rst.io/github-app-credentials-ssm-version` annotation after SSM
  credential replacement. Its SSM contract is summarized in
  [[runbooks/image-automation]] and [[runbooks/secrets-aws-ssm]].
- Grafana Microsoft Entra SSO is managed through
  `IaC/live/azuread-applications/grafana`.
- Grafana Discord alerting uses the `grafana-discord-webhook` ExternalSecret
  in `monitoring`, sourced from `/homelab/grafana/discord-webhook-url`.
  Webhook rotations require bumping the non-secret Grafana pod annotation that
  tracks the SSM parameter version because Grafana file provisioning reads the
  value at startup.
- Tailscale operator OAuth uses the `tailscale-oauth` ExternalSecret and the
  target Secret `operator-oauth`.
- cert-manager DNS-01 uses the `cert-manager-cloudflare-api-token`
  ExternalSecret and target Secret `cloudflare-api-token`.
- Deluge uses the `deluge-vpn` ExternalSecret for AirVPN WireGuard profile
  material. It reads the full profile from
  `/homelab/deluge/vpn/wireguard-config` and publishes it as `wg0.conf`. It
  refreshes on ExternalSecret changes; after replacing the SSM profile value,
  bump `homelab.rst.io/wireguard-profile-ssm-version` on both the
  ExternalSecret and Deluge pod template so the Secret is rerendered and
  Gluetun starts with the new profile. The Deluge pod resolves an endpoint DNS
  name in the profile to an IPv4 address before handing it to Gluetun.
- n8n uses `/homelab/n8n/encryption-key` as a first-boot bootstrap key only;
  existing PVCs keep using their persisted `/home/node/.n8n/config` key.
  `n8n-postgres` uses generated `/homelab/n8n/postgres-admin-password` and
  `/homelab/n8n/postgres-app-password` values; n8n receives only the app
  password through `n8n-postgres-client` and
  `DB_POSTGRESDB_PASSWORD_FILE`.
- OpenClaw uses `/homelab/openclaw/app-secret` as
  `OPENCLAW_GATEWAY_TOKEN`; bootstrap configures gateway auth with an OpenClaw
  SecretRef to that environment value instead of a generated file under the
  container user's home directory. OpenClaw uses
  `/homelab/openclaw/discord-bot-token` as `DISCORD_BOT_TOKEN`; bootstrap
  configures Discord with an OpenClaw SecretRef to that environment value
  instead of storing the token in config. ChatGPT Pro or Codex OAuth
  credentials are interactive user credentials stored on the OpenClaw PVC, not
  SSM parameters. OpenClaw GitHub App credentials use
  `/homelab/openclaw/github-app/id`,
  `/homelab/openclaw/github-app/installation-id`, and
  `/homelab/openclaw/github-app/private-key`; the ID values are env vars and
  the private key is mounted as a file referenced by
  `GITHUB_APP_PRIVATE_KEY_PATH`.
- Policy Bot runs one replica after its GitHub-App-owned SSM placeholders are
  replaced. Its SSM contract is summarized in
  [[runbooks/secrets-aws-ssm]] and [[workloads/application-notes]].
- OctoBot currently has no repository-owned SSM contract. Its first-run setup,
  exchange credentials, tentacles, and strategy state live on the finance
  namespace PVCs and are summarized in [[runbooks/secrets-aws-ssm]] and
  [[workloads/application-notes]].

## Source Files

- `docs/secrets-aws-ssm.md`
- `IaC/live/aws-ssm-parameters`
- `IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth`
- `clusters/homelab/apps/external-secrets`
