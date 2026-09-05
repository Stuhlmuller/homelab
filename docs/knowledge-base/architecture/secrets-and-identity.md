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

SSM SecureStrings now use AWS-managed `alias/aws/ssm` in `us-west-2`, selected
by `runtime_kms_key_id` in `IaC/root.hcl`. The OpenTofu client-side state key
remains `alias/homelab-opentofu` in `us-east-1`. The September migration
archives old SSM versions under AWS-managed S3 encryption before retiring
the former west-region customer key; see the audit below for rollout status.

The [[operations/kms-cost-audit-2026-09-05]] inventories three customer-managed
keys and 16 AWS-managed keys. The third customer key, `tofu-encryption-key`,
is a legacy retirement candidate, not safe to delete without checking retained
ciphertext. Account KMS costs were $3.05 in August 2026.

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

The operator-owned External Secrets permissions boundary denies direct
temporary-session requests using `aws:TokenIssueTime` only when
`aws:ViaAWSService` is false. SSM must still forward the caller's authorization
to KMS for SecureString decryption; excluding this AWS service hop from the
deny does not grant any new action or resource. Exact reader policy ARNs and
the existing boundary Allow statements still apply. On 2026-08-30, the broader
deny caused `cordium-agent-auth` refreshes to fail at `kms:Decrypt`. The
administrator applied the reviewed single-update plan from
`IaC/operator/github-actions-role-policy`; Cordium's scheduled refresh succeeded
at `2026-08-30T16:56:48Z`. The native policy regression checks all four direct
and forwarded request contexts, retaining direct temporary-credential denial.
Only Cordium refreshes periodically (every five minutes); the other 23 live
ExternalSecrets use `OnChange`. Their existing Ready conditions and the global
store's Ready status do not prove that a new decryption works under the current
boundary. After repair, verify a controlled repository-driven refresh before
rotating dependent credentials.
See [AWS forward access sessions](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_forward_access_sessions.html)
and [ViaAWSService](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html#condition-keys-viaawsservice).

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
- Argo CD Image Updater's GitHub App credential contract is retired. The
  ExternalSecret and generated Secret have no runtime consumer; Renovate owns
  image update pull requests. Its three SSM paths remain declared only as
  OpenTofu state tombstones, excluded from the External Secrets reader IAM
  policy, until a separate reviewed secret-retirement change. See
  [[runbooks/image-automation]] and [[runbooks/secrets-aws-ssm]].
- Grafana Microsoft Entra SSO is managed through
  `IaC/live/azuread-applications/grafana`. Grafana and Octelium passwords expire
  one year after creation, but their current resources have no rotation trigger;
  an unchanged apply does not rotate them. Coordinate a reviewed
  `rotate_when_changed` revision with the Grafana `OnChange` ExternalSecret and
  the Octelium native-secret sync before either expiry.
- Alertmanager owns notification delivery credentials for Grafana-managed
  alerts. The Prometheus app materializes the
  `alertmanager-discord-webhook` ExternalSecret in `monitoring`, sourced from
  `/homelab/grafana/discord-webhook-url`. Grafana routes alerts to the
  in-cluster Alertmanager contact point. External Secrets renders the Discord
  URL into Alertmanager's runtime config Secret because the Operator schema has
  no Discord URL-file field. Both routing layers repeat unresolved alerts
  hourly before Alertmanager sends the resolved notification. Alertmanager
  groups by alert name and namespace so pod-level incident fan-out does not
  exhaust Discord's webhook rate limit. Its bounded Discord template reports
  only status, alert name, namespace, and counts, avoiding oversized grouped
  payloads. Grafana
  provisioning deletes
  the retired `homelab-discord` and `homelab-openclaw-alert-hook` receiver UIDs
  so persisted Grafana PVC state does not keep retrying removed integrations.
  OpenClaw separately receives its hook token through `openclaw-secrets` as
  `GRAFANA_ALERT_HOOK_TOKEN`; bootstrap
  expands and JSON-encodes that runtime value before writing `hooks.token`,
  because OpenClaw rejects SecretRef objects for that hook-token surface.
  Alertmanager does not call the hook because its standard webhook body lacks
  OpenClaw's required `message` field.
- Tailscale operator OAuth uses the `tailscale-oauth` ExternalSecret and the
  target Secret `operator-oauth`.
- Cordium uses the `cordium-agent-auth` ExternalSecret in `octelium`, sourced
  from `/homelab/cordium/agent-auth-token`, for the policy-bound
  `homelab-cordium-agent` Workload User. The PostSync configuration hook uses
  that token only to apply the repository-owned Cordium ClusterConfig. This
  ExternalSecret polls the current SSM version every five minutes so bootstrap
  can replace the declared placeholder without a follow-up git change. The
  production apply adopts a pre-populated Cordium parameter before planning.
- The retired GitHub Actions runner no longer consumes an SSM registration
  token. `/homelab/github-actions-runner/registration-token` remains declared
  and adoptable only as an OpenTofu state tombstone because the production
  policy rejects SSM parameter deletion. It is excluded from the External
  Secrets reader IAM policy. Remove it only with a reviewed
  repository-owned state and secret-retirement workflow.
- Dispatcharr's dedicated PostgreSQL password is generated at
  `/homelab/media-postgres/dispatcharr-app-password` and rendered by
  `dispatcharr-postgres-env`; IPTV provider credentials and playlist URLs
  remain operator-configured and must not be committed.
- Multica uses generated `/homelab/multica/jwt-secret` and
  `/homelab/multica/postgres-password` values. The `multica-secrets`
  ExternalSecret in the `ai` namespace renders both parameters into the target
  Secret `multica-secrets` with `refreshPolicy: OnChange` and
  `deletionPolicy: Retain`. Rotate generated JWT and PostgreSQL values through
  the committed `IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl`
  catalog source and regenerated `IaC/live/aws-ssm-parameters` OpenTofu stack;
  do not hand-edit
  `/homelab/multica/postgres-password`, because future applies restore the
  repository-owned generated value. PostgreSQL password rotation also requires
  the database-role procedure in [[runbooks/secrets-aws-ssm]] before rolling
  consumers, since changing SSM alone does not update the retained PostgreSQL
  role on an initialized PVC. Preserve the target Secret and PostgreSQL PVC
  during rollback unless intentionally rebuilding the instance.
- NOFX uses generated `/homelab/nofx/jwt-secret`,
  `/homelab/nofx/data-encryption-key`, and
  `/homelab/nofx/rsa-private-key` values. The RSA key is a 2048-bit PEM key
  generated through the shared SSM parameter module and enables browser-side
  transport encryption without committing key material.
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
  The public API DNS reconciler reuses the cert-manager Cloudflare DNS token.
  The protected, exact-main-SHA `octelium-public-tunnel.yml` workflow uses the
  existing production AWS role for SSM reads and the `homelab-production`
  secret `CLOUDFLARE_ZONE_SETTINGS_TOKEN` for removal of retired origin/TLS
  rules (zone read, Origin Rules edit, Config Settings write). DNS reconciliation
  uses the SSM-backed DNS token. Native TLS gRPC uses the separate Tunnel TCP
  carrier; no UPnP or WAN address is required. The token values never enter git
  or workflow output. The former
  `/homelab/octelium/cloudflare-zone-settings-token` declaration has no runtime
  consumer, is excluded from the External Secrets reader IAM policy, and
  remains only until secret retirement is reviewed separately.
  Octelium portal login uses Microsoft Entra OIDC. The Entra application is
  managed by `IaC/live/azuread-applications/octelium` and writes generated
  client material to `/homelab/octelium/entra/*`; these values are copied into
  the Octelium native Secret `entra-oidc-client-secret` and IdentityProvider
  `entra` by `scripts/octelium-entra-oidc.sh`. HUMAN user Entra identifiers are
  runtime mappings and must not be committed to the public repo.
  GitHub Actions uses a separate Octelium workload credential for User
  `homelab-ci`, Policy `homelab-ci-kubernetes-api-access`, and Service
  `kubernetes-api-ci`. Store the credential only as GitHub environment
  secret `OCTELIUM_CI_AUTH_TOKEN` for `homelab-plan` and
  `homelab-production`. Both environments require reviewer approval before
  GitHub releases the token; approve a pull request plan only after reviewing
  its exact code because that job also assumes the environment-bound AWS OIDC
  identity. Repository Actions policy rejects mutable action tags, and the
  `main` ruleset requires signed, squash-only pull requests with strict
  always-on checks and no force pushes. The CI connector does not pass Octelium
  `--scope` flags on v0.35. Its Session policy requires the exact WORKLOAD User,
  CLIENTLESS Session, `kubernetes-api-ci.default` Service, and KUBERNETES mode;
  it must not grant the bearer access to other public Services. The User owns
  matching 30-day clientless-session and access-token lifetimes. Rotate it every
  21 days with
  `scripts/octelium-ci-credential.sh`; the helper deletes the dedicated User's
  Sessions first so Octelium cannot retain an older Session expiry, then retries
  GitHub environment writes until both store the replacement token.
  Octelium Secret `homelab-ci-kubeconfig` stores the upstream credential shared
  by `kubernetes-api-ci` and private Service `kubernetes-api.homelab`; clients
  receive only Octelium-generated kubeconfigs. Recreating the Secret briefly
  affects CI, operator, and Cordium Kubernetes access, so validate both Services
  after rotation.
- Focused reconciliation of `homelab-private-kubernetes-access` and
  `kubernetes-api.homelab` uses the separate `homelab-catalog-ci` workload User
  and `homelab-private-kubernetes-ci` AUTH_TOKEN Credential. The Credential is
  limited to one authentication, expires after 30 minutes, auto-deletes on
  login, and copies a highest-priority, fail-closed six-method Policy/Service
  API policy into a 15-minute client Session. Its helper-only template is kept
  outside the general Octelium catalog with an already-expired timestamp; only
  the lifecycle helper replaces that timestamp and applies it. The
  protected `homelab-production` secret
  `OCTELIUM_CATALOG_AUTH_TOKEN` exists only between provisioning and the
  mandatory revoke step. Octelium v0.35 cannot scope these methods by object
  name; the fixed helper, reviewed hashes, exact `main` SHA, and production
  approval provide that boundary. See `docs/ci-cd.md`.
  The self-hosted Octelium Cluster storage layer uses generated
  `/homelab/octelium/postgres-password` and
  `/homelab/octelium/redis-password` values materialized by
  `octelium-storage-auth`; `scripts/octelium-cluster-bootstrap.sh` reads those
  Kubernetes Secret values into a temporary `octops init` bootstrap file that is
  never committed.
  Octelium Enterprise license material, if required for commercial or
  production use, also stays outside git; add only a safe SSM or
  ExternalSecret contract in a future change if the package needs one.
- The GitHub Actions AWS OIDC apply role is an operator-owned bootstrap
  identity. `IaC/operator/github-actions-role-policy` owns the existing
  `Github-TF-State` role's trust policy and additive SSM reader-policy lifecycle
  grant. Trust is limited to `homelab-plan`, `homelab-production`,
  `github-iac-plan`, and `github-iac-production`. Apply trust changes only with
  a reviewed administrator session and the single-role saved-plan gate in
  `IaC/operator/README.md`; the first rollout must import the existing role
  before planning. CI must not traverse `IaC/operator` or gain permission to
  replace its own attachment. The
  grant is bounded to policy slots `00` through `09` and the exact
  `homelab-ssm-parameter-readers` group. The unit also adopts
  `external-secrets_aws-ssm-auth`, removes direct user policies, and caps it
  with an operator-owned boundary that allows only homelab SSM reads and
  runtime-secret KMS decrypt/describe access. The boundary denies direct
  temporary STS requests while preserving SSM's AWS-managed KMS calls, and the
  reader policy excludes the two parameters that hold
  this user's own key so a compromised key cannot copy its replacement. The
  pending administrator rollout remains tracked in
  [[../operations/continuous-improvement]].
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
  is the only Deluge VPN parameter readable by External Secrets; the six
  retired split-profile parameters remain non-readable state tombstones. It
  refreshes on ExternalSecret changes; after replacing the SSM profile value,
  bump `homelab.rst.io/wireguard-profile-ssm-version` on both the
  ExternalSecret and Deluge pod template so the Secret is rerendered and
  Gluetun starts with the new profile. Its startup wrapper extracts the private
  key, preshared key, and first IPv4 interface address, while Gluetun's native
  AirVPN provider selects the server. The profile's endpoint and server key are
  not used, avoiding custom-provider DNS resolution during sidecar recovery.
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
  installs the exact image-version official external Discord package from npm
  into pod-local storage before config validation without a floating fallback,
  then configures Discord with an OpenClaw SecretRef to that environment value
  instead of storing the token in config. The bootstrap and proxy containers
  do not receive the app-only LiteLLM, Grafana-login, or GitHub App credentials,
  and the proxy does not mount persistent OpenClaw state. ChatGPT Pro or Codex OAuth
  credentials are interactive user credentials stored on the OpenClaw PVC, not
  SSM parameters. OpenClaw GitHub App credentials use
  `/homelab/openclaw/github-app/id`,
  `/homelab/openclaw/github-app/installation-id`, and
  `/homelab/openclaw/github-app/private-key`; the ID values are env vars and
  the private key is mounted into the app as a file referenced by
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

## NOFX native reconciliation boundary

NOFX anonymous-access removal is applied by the fixed repository operator
command, independently from Kubernetes Argo CD. It requires an exact reviewed
main commit, selects only `nofx.default`, proves a second apply is empty, and
verifies the human-access policy. Existing operator credentials stay private;
the temporary native transport changes no saved host or client settings.
See [NOFX reconciliation](../../octelium-nofx-reconciliation.md).
