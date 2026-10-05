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

- Fleet uses five generated `/homelab/fleet/` SSM values: database user/root
  passwords, Redis password, a stable 32-byte server encryption key and initial
  administrator password. Namespace `fleet` has a scoped store/policy contract.
  Separate mounted Secrets keep the root password out of Fleet and the admin
  password exclusively in its one-time bootstrap Job. The initial account uses
  `rodman@stuhlmuller.net`; subsequent syncs preserve user changes. APNs and
  platform signing identities still require their provider setup. Preserve them
  with the database and server key. See the [Fleet runbook](../../../clusters/homelab/apps/fleet/README.md).
  The repository-owned `scripts/fleet-download-apple-csr.py` prepares Apple's
  vendor-signed CSR using the initial administrator Secret without printing
  credentials. Its first request creates encrypted SCEP/APNs keys in MySQL;
  preserve that database with the server encryption key. The public CSR goes
  to Fleet's signing service; the operator must still issue the APNs certificate
  through their Apple account and upload it in Fleet before device enrollment.
  Its `--certificate` mode performs first activation through Fleet's APNs setup
  API, refuses to overwrite an enabled integration, verifies enabled state and
  certificate metadata, and revokes its session. Certificate renewal remains
  the documented Fleet UI flow using the same Apple account. APNs material
  stays encrypted in MySQL and outside git.

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
- Entra provider identities are operator-owned Terraform resources under
  `IaC/operator/azuread-ci-identities`. Separate plan/apply applications trust
  only their exact protected GitHub environments; no client secret, paid license
  or CI self-grant permission is configured. Stable application ownership
  preserves the human administrator when switching provider identities. GitHub
  environment protection remains owned by `Stuhlmuller/github-iac`. Follow the
  [provider runbook](../../../docs/entra-terraform-provider.md) for the bootstrap,
  permission limits and independent CI OIDC acceptance gates.
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
- Bazarr reads Sonarr/Radarr API keys from their existing local `config.xml`
  files through read-only init-container mounts. It retains credentials only in
  its private config volume; no new SSM parameter or direct environment-variable
  secret injection is introduced. The main container never mounts either source
  config claim. The private `bazarr.default` Octelium WEB Service requires the
  existing `homelab-human-web-access` policy; it has neither anonymous access nor
  a public DNS/tunnel route. Config backups contain these credentials and must
  remain private.
- Dispatcharr's dedicated PostgreSQL password is generated at
  `/homelab/media-postgres/dispatcharr-app-password` and rendered by
  `dispatcharr-postgres-env`; IPTV provider credentials and playlist URLs
  remain operator-configured and must not be committed.
- Multica uses generated `/homelab/multica/jwt-secret`,
  `/homelab/multica/postgres-password`, and six-digit
  `/homelab/multica/dev-verification-code` values. ExternalSecrets in `ai`
  render the database credentials into `multica-secrets` and backend credentials
  plus the fixed code into `multica-backend-secrets`, both with
  `refreshPolicy: OnChange` and `deletionPolicy: Retain`. The new backend Secret
  prevents starting before the fixed code is present; PostgreSQL retains its
  original Secret. Rotate generated JWT and PostgreSQL values through
  the committed `IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl`
  catalog source and regenerated `IaC/live/aws-ssm-parameters` OpenTofu stack;
  do not hand-edit
  `/homelab/multica/postgres-password`, because future applies restore the
  repository-owned generated value. PostgreSQL password rotation also requires
  the database-role procedure in [[runbooks/secrets-aws-ssm]] before rolling
  consumers, since changing SSM alone does not update the retained PostgreSQL
  role on an initialized PVC. Preserve the target Secret and PostgreSQL PVC
  during rollback unless intentionally rebuilding the instance. The backend
  uses `APP_ENV=development` to accept the private fixed code without email
  delivery; the code-entry screen remains. Octelium gates access, but code
  holders with access can impersonate existing Multica users. Keep this limited
  to trusted operators; restore production mode and a real email/OAuth provider
  before regular multi-user use. See the [Multica runbook](../../../clusters/homelab/apps/multica/README.md).
  Native desktop access requires an authenticated Octelium CLIENT session;
  exposing Multica auth or API paths outside Octelium would make the shared code
  an unsafe public credential.
  The server runtime uses only the fixed-code key in an init container to
  bootstrap a 90-day Rodman PAT, then retains that PAT privately on its own
  local PVC. The daemon renews it; revoked or expired tokens fail startup
  rather than silently creating a replacement. The main container exposes only
  its own profile, including native ChatGPT OAuth state retained on the runtime
  PVC; it does not mount the backend JWT, database password, fixed code, or a
  model API key. This remains a trusted operator runtime because tasks can read
  that profile. Its dedicated ServiceAccount has no Kubernetes token and
  receives explicit Istio access only to the Multica backend. OAuth is created
  through an interactive Codex device login and must not be copied into SSM or
  a Kubernetes Secret.
- NOFX uses generated `/homelab/nofx/jwt-secret`,
  `/homelab/nofx/data-encryption-key`, and
  `/homelab/nofx/rsa-private-key` values. The RSA key is a 2048-bit PEM key
  generated through the shared SSM parameter module and enables browser-side
  transport encryption without committing key material.
  Its private maintained images use the read-only Harbor robot through the
  namespace-scoped `harbor-pull` Secret, referenced only by `imagePullSecrets`.
  The retained GHCR recovery path uses a separate, externally issued
  `/homelab/nofx/ghcr-read-token`. The protected `NOFX Registry Credential`
  workflow validates a dedicated classic PAT with only `read:packages` before
  updating that exact SecureString. `nofx-registry-auth` refreshes every five
  minutes and renders a kubelet-only Docker config Secret. A GHCR rollback must
  switch image references and pull Secret together after authenticated pulls
  and a fresh successful Secret refresh. Bootstrap
  PR #1031 retained upstream images while establishing this credential path;
  see the [private-image runbook](../../nofx-private-images.md).
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
  `homelab-ssm-parameter-readers` group, plus metadata-only `kms:DescribeKey`
  on the resolved current runtime-secret key. The September 29, 2026 Langfuse
  apply reached SSM refresh but its identity policy still covered only the old
  runtime key. The correction reuses the operator-owned policy and attachment;
  it adds no cryptographic or key-administration permission. Apply only the
  reviewed single-policy saved-plan update through
  [the operator runbook](../../../IaC/operator/README.md#full-unit-reconciliation),
  never CI self-administration; stop on unrelated drift. On September 30, 2026
  PDT (October 1 UTC), the saved plan applied and a fresh full-unit plan was a
  no-op; CI simulation allows only `kms:DescribeKey` on the current SSM key,
  with `kms:Decrypt` and `kms:ScheduleKeyDeletion` implicitly denied. The unit also adopts
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
- Langfuse keeps application, datastore, project and headless-init credentials
  under `/homelab/langfuse/`; its namespace consumes `langfuse-secrets`.
  `IaC/live/langfuse-blob-storage` owns the distinct S3 runtime credential pair.
  On September 30, 2026 PDT (October 1 UTC), an administrator applied its
  reviewed 12-resource bootstrap through the normal remote state; a fresh plan
  was a no-op and live checks confirmed public-access blocks, versioning, and
  both exact S3 SSM parameters as current SecureStrings under `alias/aws/ssm`.
  After a reviewed operator apply adds the pending grant, CI can use only
  `iam:GetUser`, `iam:ListAccessKeys`, and
  `iam:GetUserPolicy` on
  `arn:aws:iam::716182248480:user/homelab/homelab-langfuse-s3` for Langfuse-user
  refresh. This additional grant has no IAM write, tag, wildcard, or other-user
  permission. Future Langfuse IAM lifecycle or credential-rotation changes
  remain operator-owned through the same saved-plan path.
- LiteLLM caller keys are generated separately for NOFX, Multica and n8n at
  `/homelab/<app>/litellm-token`; OpenClaw uses
  `/homelab/openclaw/litellm-app-token`. The prior OpenClaw `litellm-token`
  remains a retired master-key alias with no workload consumer. LiteLLM alone
  receives the existing `/homelab/litellm/openai-api-key` provider credential
  and Langfuse project keys. Its pre-auth guard prevents callers from choosing
  a provider, collector, or identity. See [[ai-observability]] for acceptance
  evidence and accounting scope.
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
  Its dedicated `/homelab/n8n/litellm-token` is rendered only as an OpenAI
  credential overwrite for the internal LiteLLM endpoint; it is never stored
  in workflow JSON or the n8n credential database.
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
  and the proxy does not mount persistent OpenClaw state. The deployed assistant
  does not configure ChatGPT Pro or Codex OAuth inference. OpenClaw GitHub App credentials use
  `/homelab/openclaw/github-app/id`,
  `/homelab/openclaw/github-app/installation-id`, and
  `/homelab/openclaw/github-app/private-key`; the ID values are env vars and
  the private key is mounted into the app as a file referenced by
  `GITHUB_APP_PRIVATE_KEY_PATH`. The managed `assistant/gh` wrapper exchanges
  that key for a homelab-only installation token on each CLI/Git invocation.
  Tokens use private temporary CLI config files, never the PVC or child process
  environment; requests omit administration and secret-management permissions.
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

## Dedicated Cordium CI assertion

`homelab-cordium-ci-oidc` accepts GitHub assertions only for the exact repository,
owner, main workflow, audience, and dispatch event. `homelab-cordium-ci` is a
separate workload identity with bounded sessions and workspace lifecycle/exec
permissions; bootstrap management credentials are not shared. A catch-all
post-authentication denial and priority -4 method denial close upstream
default allowances. The fixed `scripts/cordium-ci-reconcile.py` path previews
only these three resources by default. Execution requires clean, exact reviewed
main, applies Policy before IdentityProvider and User, proves repeated-apply
convergence, and verifies the declared specifications. It never applies the
full catalog or creates credentials. A 2026-09-12 authenticated read-only
preview found all three resources absent; native installation and live OIDC
acceptance remain pending. See
[the contract and pending live gates](../../cordium-ci.md).

## NOFX native reconciliation boundary

NOFX anonymous-access removal is applied by the fixed repository operator
command, independently from Kubernetes Argo CD. It requires an exact reviewed
main commit, selects only `nofx.default`, proves a second apply is empty, and
verifies the human-access policy. Existing operator credentials stay private;
the temporary native transport changes no saved host or client settings.
See [NOFX reconciliation](../../octelium-nofx-reconciliation.md).

## Fleet Free identity boundaries

The [WireGuard/AirVPN operator](../../../clusters/homelab/apps/fleet/WIREGUARD-AIRVPN.md)
accepts private owner-supplied client exports from outside git, separately per
device. It builds the credential-bearing Apple profile in memory and sends it
only to the selected device. Fleet command data, database backups, and device
profiles/keychain can contain the VPN material and require credential-level
protection. The public catalog contains only app links and a reporting policy;
there is no global private-profile upload, Deluge secret reuse, or new SSM
contract. Removing a device profile does not revoke its AirVPN client key.

Its optional `--password-file` supplies the existing Fleet administrator's
current password after rotation, replacing the bootstrap-secret source without
fallback, login retries, or credential rotation. The owner-only `0600` UTF-8
file must be outside the repository and at most 4096 bytes, with one password
line; one final LF/CRLF is ignored and spaces are preserved. Dry runs read
neither credential source. Omitting the option uses the initial administrator
secret and works only while that password remains current.

See the [Free Entra runbook](../../../clusters/homelab/apps/fleet/FREE-ENTRA.md).
Native Microsoft Password Platform SSO uses Company Portal's extension and each
person's Entra account. It preserves the existing local Mac account; no Fleet
Premium password-sync or Intune enrollment is configured. Registration alone
does not establish management or compliance. Password, offline login and
FileVault acceptance require interactive tests.

Console SAML is a separate `azuread-applications/fleet` Terragrunt unit. Its
single-tenant enterprise application requires individual assignment, selects a
Microsoft-generated signing certificate declaratively, and exposes only sensitive
runtime metadata outputs. The initial Fleet administrator remains a recovery
account; only the authorized Entra identity is precreated as an SSO administrator.
JIT/SCIM provisioning stays disabled. The public native-client route continues
without Octelium redirects; Fleet authenticates administrative requests.

Read-only inspection found Entra Free and enabled Security Defaults. The existing
tenant owner is an external Microsoft-account member, not an internal cloud
password identity. Preserve it; use the separately authorized native pilot
account for Mac Password SSO. Do not infer password support from `UserType=Member`
alone, weaken MFA, or convert/reset the existing tenant administrator.
The `azuread-applications/fleet-pilot-user` unit stays in the existing AzureAD
CI collection despite owning a user. It grants no role, group or license, protects
against destruction, and ignores later password changes. Its generated initial
password remains in encrypted state and a private handoff file; it must be changed
interactively before PSSO. Family identities beyond the pilot require explicit
names and must not inherit console administrator access.

The separate `operator/entra-stuhlmuller-domain` unit reads the existing
`stuhlmuller.net` Entra domain as a non-default managed domain. It reads the
Microsoft Graph TXT verification record, does not configure email, federation,
or Google Workspace, and keeps verification disabled until the DNS owner has
applied that record through its own reviewed declarative path. Once both
authoritative servers return it, the reviewed phase-two catalog change enables
the sole Graph verification action. That action intentionally uses the
standard bodyless Graph request, retaining the service default of no domain
takeover; its private saved plan must confirm the domain remains managed and
non-default. The companion
`operator/entra-stuhlmuller-pilot-user` unit can then create only
`rodman.mac@stuhlmuller.net`. Its domain guard requires verified managed,
non-default state, and the account receives no role, group, license, mailbox or
Fleet-console assignment. Existing Google/Entra users stay untouched; a Google
email address alone is not an Entra password identity. Its guarded module is
separate from the legacy AzureAD user module, and the AzureAD workflow selects
that collection only when its own source or plan inputs change; an operator-only
pilot change cannot trigger legacy-user reconciliation.

## Harbor registry identities

[[../operations/harbor-oci|Harbor]] uses generated SSM secrets under
`/homelab/harbor/`, file-mounted bootstrap credentials, a private project, and
separate project robots for pull and publication. NOFX receives only the pull
credential through `/homelab/nofx/harbor-pull-password`. Octelium passes native
Authorization headers; Harbor authenticates OCI clients. Registration is
disabled and project creation is admin-only. Public upstream copies use the
separate public-read `mirror` project; `robot$mirror+publisher` uses its own generated
`/homelab/harbor/mirror-robot-push-password` and is scoped only to that project. Nodes need no new secret.
Bootstrap and Harbor recovery use the reviewed upstream transport rollback;
see [the image mirror runbook](../../harbor-image-mirroring.md).

Harbor OCI signing uses a separate cert-manager-generated P-256 key in the
`harbor-image-signing` Kubernetes Secret, with key rotation disabled during
certificate renewal. The protected in-cluster signing Job mounts that key;
CI receives only its public half through Pod status and verifies signatures.
No AWS signing resource or public transparency log is used. Namespace Pod
creators and cluster administrators can access the key: keep those permissions
restricted, back up etcd to encrypted off-node storage, and retain trusted public
keys independently. See [[../operations/harbor-oci]] for rollout acceptance.
