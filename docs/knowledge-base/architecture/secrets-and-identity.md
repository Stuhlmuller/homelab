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
- The External Secrets IAM reader keeps exact parameter ARNs in sorted,
  deterministic customer-managed policy chunks of at most 25 names; it does
  not use a `/homelab/*` wildcard.
- Reader policy preconditions enforce AWS IAM's 6,144-character limit per
  customer-managed policy and 10 managed policies per group. The expanding
  parameter list is not split into group inline policies because their combined
  aggregate limit is 5,120 characters; the existing fixed-size inline policy
  retains only exact KMS-key permissions and is updated after the managed
  policies are attached.

## Identity Notes

- Argo CD SSO uses the `argocd-oidc-sso` ExternalSecret for the upstream OIDC
  issuer compatibility copy, client ID, and client secret. Dex startup uses the
  literal Microsoft Entra issuer committed in
  `IaC/bootstrap/argocd/terragrunt.hcl` so a placeholder SSM value cannot stop
  provider discovery. Microsoft Entra group authorization is a token-claim
  behavior, not a requested OAuth scope: keep Dex scopes to `openid`,
  `profile`, and `email`, configure Entra to emit the `groups` claim for Argo
  CD RBAC, and keep `insecureSkipEmailVerified: true` because Entra may omit
  the `email_verified` claim. The bootstrap RBAC policy also binds
  `rodman@stuhlmuller.net` directly to `role:admin` through the configured
  `email` scope so operator access does not depend on group-claim setup.
- Argo CD Image Updater uses the `argocd-image-updater-git` ExternalSecret for
  GitHub App credentials that open image update pull requests through Git
  write-back. It refreshes on ExternalSecret changes; bump the non-secret
  `homelab.rst.io/github-app-credentials-ssm-version` annotation after SSM
  credential replacement. Its SSM contract is summarized in
  [[runbooks/image-automation]] and [[runbooks/secrets-aws-ssm]].
- Grafana Microsoft Entra SSO is managed through
  `IaC/live/azuread-applications/grafana`.
- Alertmanager owns notification delivery credentials for Grafana-managed
  alerts. The Prometheus app materializes `alertmanager-discord-webhook` and
  `alertmanager-openclaw-alert-hook` ExternalSecrets in `monitoring`, sourced
  from `/homelab/grafana/discord-webhook-url` and
  `/homelab/grafana/openclaw-alert-hook-token`. Grafana routes alerts to the
  in-cluster Alertmanager contact point, Alertmanager fans out with file-backed
  credentials, and Grafana provisioning deletes the retired `homelab-discord`
  and `homelab-openclaw-alert-hook` receiver UIDs so persisted Grafana PVC state
  does not keep retrying removed integrations. OpenClaw receives the same hook
  token through `openclaw-secrets` as `GRAFANA_ALERT_HOOK_TOKEN`; bootstrap
  expands and JSON-encodes that runtime value before writing `hooks.token`,
  because OpenClaw rejects SecretRef objects for that hook-token surface.
- Tailscale operator OAuth uses the `tailscale-oauth` ExternalSecret and the
  target Secret `operator-oauth`.
- The `github-actions-runner` app uses the
  `github-actions-runner-registration` ExternalSecret, sourced from
  `/homelab/github-actions-runner/registration-token`, to bootstrap the
  self-hosted runner. The registration token is short-lived and is only needed
  when recreating runner registration state; the runner workspace is ephemeral
  and stores no durable token material.
- Octelium client bridge auth uses the `octelium-client-auth` ExternalSecret in
  `octelium-client`, sourced from `/homelab/octelium/client-auth-token` and
  rendered to the versioned target Secret `octelium-client-auth-v5`. The token
  belongs to the Octelium workload User `homelab-octelium-client` and is
  created outside git with `octeliumctl`.
  Public Octelium control-plane access uses the
  `octelium-public-cloudflared-credentials` ExternalSecret in
  `octelium-public`, sourced from
  `/homelab/octelium/cloudflare-tunnel-credentials-json` and
  `/homelab/octelium/cloudflare-tunnel-id`. The Cloudflare Tunnel credential
  JSON and UUID are created outside git with `cloudflared tunnel create
  homelab-octelium-public`. The same tunnel is the external callback backbone
  for `n8n-webhook.stinkyboi.com` and `policy-bot-hook.stinkyboi.com`; those
  routes remain unauthenticated at Octelium but path-limited in Istio and
  validated by the receiving application credentials or signatures.
  Octelium portal login uses Microsoft Entra OIDC. The Entra application is
  managed by `IaC/live/azuread-applications/octelium` and writes generated
  client material to `/homelab/octelium/entra/*`; these values are copied into
  the Octelium native Secret `entra-oidc-client-secret` and IdentityProvider
  `entra` by `scripts/octelium-entra-oidc.sh`. HUMAN user Entra identifiers are
  runtime mappings and must not be committed to the public repo.
  GitHub Actions uses a separate Octelium workload credential for User
  `homelab-ci`, Policy `homelab-ci-kubernetes-api-access`, and Service
  `kubernetes-api.ci`. Store the credential only as GitHub environment
  secret `OCTELIUM_CI_AUTH_TOKEN` for `homelab-plan` and
  `homelab-production`; the CI connector does not pass Octelium `--scope`
  flags on v0.35, while the policy-bound credential authorizes the Connect API
  method and Kubernetes API Service separately. Rotate it with
  `scripts/octelium-ci-credential.sh` after applying catalog policy changes so
  the GitHub environments receive a token created against the current policy.
  The self-hosted Octelium Cluster storage layer uses generated
  `/homelab/octelium/postgres-password` and
  `/homelab/octelium/redis-password` values materialized by
  `octelium-storage-auth`; `scripts/octelium-cluster-bootstrap.sh` reads those
  Kubernetes Secret values into a temporary `octops init` bootstrap file that is
  never committed.
  Octelium Enterprise license material, if required for commercial or
  production use, also stays outside git; add only a safe SSM or
  ExternalSecret contract in a future change if the package needs one.
- cert-manager DNS-01 uses the `cert-manager-cloudflare-api-token`
  ExternalSecret and target Secret `cloudflare-api-token`.
- AFFiNE uses generated `/homelab/affine/postgres-password`,
  `/homelab/affine/redis-password`, and `/homelab/affine/private-key` values.
  The private key is a P-256 ECDSA PEM generated by OpenTofu, encrypted in SSM,
  and materialized by `affine-secrets`; it must remain stable because AFFiNE
  uses it for token signing and application-data encryption.
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
  [[runbooks/secrets-aws-ssm]] and [[workloads/application-notes]]. Configure
  the GitHub App webhook URL to
  `https://policy-bot-hook.stinkyboi.com/api/github/hook` after the
  `octelium-public` DNS/tunnel route is live; keep the webhook secret in
  `/homelab/policy-bot/github-app/webhook-secret`.
- OctoBot currently has no repository-owned SSM contract. Its first-run setup,
  exchange credentials, tentacles, and strategy state live on the finance
  namespace PVCs and are summarized in [[runbooks/secrets-aws-ssm]] and
  [[workloads/application-notes]].

## Source Files

- `docs/secrets-aws-ssm.md`
- `IaC/live/aws-ssm-parameters`
- `IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth`
- `clusters/homelab/apps/external-secrets`
