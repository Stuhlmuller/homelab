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

## AWS SSM Pattern

- Public parameter prefix: `/homelab/<app>/<name>`
- Region: `us-west-2`
- Runtime secret values live outside git.
- ExternalSecret namespace access is constrained by the `aws-ssm`
  ClusterSecretStore namespace allow-list.
- Add a namespace to that allow-list in the same change that adds its first
  ExternalSecret.

## Identity Notes

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
- n8n uses `/homelab/n8n/encryption-key` as a first-boot bootstrap key only;
  existing PVCs keep using their persisted `/home/node/.n8n/config` key.
- OpenClaw uses `/homelab/openclaw/discord-bot-token` as
  `DISCORD_BOT_TOKEN` for startup Discord channel registration. ChatGPT Pro or
  Codex OAuth credentials are interactive user credentials stored on the
  OpenClaw PVC, not SSM parameters.
- Policy Bot runs one replica after its GitHub-App-owned SSM placeholders are
  replaced. Its SSM contract is summarized in
  [[runbooks/secrets-aws-ssm]] and [[workloads/application-notes]].
- Hummingbot is an in-flight app addition in the current working tree. Its SSM
  contract is summarized in [[runbooks/secrets-aws-ssm]] and
  [[workloads/application-notes]].

## Source Files

- `docs/secrets-aws-ssm.md`
- `IaC/live/aws-ssm-parameters`
- `IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth`
- `clusters/homelab/apps/external-secrets`
