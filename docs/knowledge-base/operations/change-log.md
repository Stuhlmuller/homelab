# Knowledge Base Change Log

Tags: #operations #knowledge-base

Record entries when a change creates, removes, renames, or materially changes an
app, platform dependency, workflow, topology assumption, secret contract,
storage requirement, or validation gate.

Use [[templates/knowledge-update]] for new entries.

## Entries

### 2026-05-28 - Add OpenClaw GitHub App secret contract

- Added OpenClaw SSM placeholders for GitHub App ID, installation ID, and
  private key PEM.
- Exposed the GitHub App IDs through `openclaw-secrets`, mounted the private
  key from a separate Secret as a file, and added
  `GITHUB_APP_PRIVATE_KEY_PATH` for the app and bootstrap containers.
- Updated OpenClaw app docs and secret-contract notes with the rollout
  annotation to bump after replacing SSM placeholders.

### 2026-05-26 - Make Terragrunt apply non-interactive

- Added `--non-interactive` to stack-wide production apply phases so
  Terragrunt accepts the `run --all` apply queue in GitHub Actions before
  forwarding OpenTofu flags.
- Updated the CI/CD runbook note with the final non-interactive command shape.

### 2026-05-26 - Enable OpenClaw memory wiki

- Enabled OpenClaw's bundled `memory-wiki` plugin during pod startup bootstrap
  so Imported Insights and Memory Palace are available from the Control UI.
- Updated OpenClaw app docs and workload notes to keep the UI reload step tied
  to the repo-owned config path.
### 2026-05-26 - Increase OpenClaw resource profile

- Added explicit OpenClaw app resources for Codex-backed agent work: `1` CPU
  and `2Gi` memory requested, `6Gi` memory limit, and no CPU limit so work can
  burst when node capacity is available.
- Added bootstrap init-container resources so config validation and channel
  plugin installation have `500m` CPU and `1Gi` memory requested with a `3Gi`
  memory limit.
- Added a small proxy resource profile and documented the allocation in the
  OpenClaw README and workload knowledge-base notes.
### 2026-05-26 - Forward Terragrunt apply flags explicitly

- Updated `scripts/ci/terragrunt-apply.sh` so stack-wide apply phases call
  `terragrunt run --all -- apply -no-color -auto-approve`, matching
  Terragrunt 1.x flag parsing and forwarding OpenTofu flags correctly.
- Documented the flag-forwarding requirement in the CI/CD runbook note.

### 2026-05-26 - Clarify SSM KMS apply-role access

- Documented that `IaC/live/aws-ssm-parameters` uses a `us-west-2` SSM
  SecureString KMS key under `alias/homelab-opentofu`, separate from the
  `us-east-1` OpenTofu state key with the same alias.
- Added troubleshooting guidance for production applies that fail during SSM
  state refresh with `kms:DescribeKey` denied on the `us-west-2` key.

### 2026-05-26 - Accept secret fallback for Terragrunt CI inputs

- Updated the trusted PR plan and protected production apply workflows so
  non-sensitive role, client, and tenant identifiers can come from GitHub
  variables or same-named secrets.
- Added early input checks before AWS role assumption so missing GitHub
  environment configuration fails before tailnet or live Terragrunt work starts.
- Kept post-merge applies moving when Entra credentials are not configured by
  skipping the AzureAD phase only for pushes that did not touch the AzureAD
  stack.
- Consolidated plan and apply AWS role selection on `AWS_ROLE_TO_ASSUME_HOMELAB`
  so the same GitHub variable can drive both trusted PR plans and production
  applies.

### 2026-05-26 - Replace Hummingbot with OctoBot UI

- Replaced the finance namespace Hummingbot CLI workload with OctoBot using
  `drakkarsoftware/octobot:2.1.1`, NFS-backed `user`, `tentacles`, and `logs`
  PVCs, and the tailnet-only `https://octobot.stinkyboi.com` Istio route.
- Retired the Hummingbot workload into a PVC-only Argo CD Application so Argo
  prunes the old Deployment, Service, ExternalSecret, and route while keeping
  rollback data protected.
- Kept `/homelab/hummingbot/config-password` declared while the retired
  Hummingbot PVCs exist; OctoBot setup and exchange credentials are UI-managed
  runtime state on OctoBot PVCs.
- Updated app inventory, storage, ingress, image automation, runtime isolation,
  rollback, and secrets notes so OctoBot is the current finance app.

### 2026-05-26 - Restore OpenClaw Codex subscription route

- Updated OpenClaw from `2026.3.1` to `2026.5.22` so the bundled `codex`
  plugin is available for ChatGPT/Codex subscription auth.
- Added startup bootstrap config for `plugins.entries.codex.enabled` and the
  canonical `openai/gpt-5.5` default model route.
- Added a safe OpenClaw doctor repair during bootstrap so stale PVC config
  schemas are migrated before writing new defaults.
- Added `gateway.mode=local` to the bootstrap defaults for the
  container-managed gateway process.
- Moved OpenClaw's npm plugin cache and extension directory to pod-local
  `emptyDir` storage so channel plugins are not blocked by QNAP NFS `nobody`
  ownership.
- Made bootstrap install and enable `@openclaw/discord`, then configure
  `channels.discord.token` as a SecretRef to `DISCORD_BOT_TOKEN`.
- Updated OpenClaw operator docs and app notes so Codex OAuth remains
  PVC-backed runtime state instead of an SSM secret or committed API key.

### 2026-05-26 - Add Kiali mesh UI

- Added the `kiali` Argo CD Application and desired state using the official
  Kiali operator Helm chart.
- Exposed Kiali at `https://kiali.stinkyboi.com` through the tailnet-only Istio
  gateway with anonymous read-only access.
- Updated monitoring AuthorizationPolicies so Kiali can query Grafana and
  Prometheus without opening direct Prometheus ingress.

### 2026-05-26 - Serialize trusted Terragrunt PR plans

- Added a shared concurrency gate to the trusted PR `Terragrunt Plan` job so
  simultaneous Renovate branches queue before reading the shared OpenTofu S3
  backend state.
- Changed same-PR workflow concurrency to queue replacement runs instead of
  canceling active runs, because canceling a live OpenTofu plan can strand an
  S3 backend lock.
- Documented that queued Terragrunt PR plans are expected when another trusted
  PR is already holding the live-state lock lane.

### 2026-05-25 - PR Conftest ordering

- Split Conftest policy evaluation out of `scripts/ci/static-checks.sh` into
  `scripts/ci/conftest-policies.sh`.
- Updated the pull request Terragrunt Plan workflow so trusted same-repository
  PRs run Conftest after the live Terragrunt plan step while forked PRs still
  run Conftest without receiving live-plan secrets.

### 2026-05-25 - Move Servarr media library to QNAP Media export

- Added static media PV/PVC desired state for Deluge downloads, Radarr movies,
  and Sonarr TV library data against the QNAP `/media` export.
- Added migration Jobs that copy the old dynamic PVC contents into `/media`,
  set NFS-safe write permissions, and verify target writes before app cutover.
- Kept the old dynamic media PVCs in desired state as rollback sources until
  the `/media` migration is verified.
- Documented the 2026-05-26 read-only `showmount -e 10.1.0.2` check that
  verified `/media` and `/homelab` are exported to the Talos nodes.

### 2026-05-25 - Add Hummingbot tailnet status route

- Added a tailnet-only Istio route at `https://hummingbot.stinkyboi.com` backed
  by a `route-status` sidecar on the Hummingbot pod.
- Kept interactive trading access on `kubectl attach`; the route is not the
  Hummingbot API and does not expose exchange credentials or trading controls.
- Added a repo-owned `finance` namespace manifest with baseline Pod Security
  labels and recorded the route in ingress, runtime-isolation, image-updater,
  and workload notes.

### 2026-05-25 - Clarify Policy Bot GitHub App identity

- Documented that Policy Bot's `integration_id` setting maps to the GitHub App
  ID, not the installation ID or OAuth client ID.
- Added the `404 Integration not found` startup failure mode so future repairs
  check the GitHub App ID/private-key pairing before troubleshooting ingress or
  External Secrets.
- Recorded the `refreshPolicy: OnChange` follow-up so SSM repairs are rolled
  through a repo-owned ExternalSecret change and Argo CD sync.

### 2026-05-25 - Preserve runtime security audit WIP

- Preserved namespace Pod Security hardening so non-privileged namespaces keep
  `baseline` enforcement while warning and auditing against `restricted`.
- Preserved service-account token and Istio LoadBalancer node-port hardening
  notes from the audit worktree for review in a dedicated draft PR.

### 2026-05-25 - Enable Policy Bot replica

- Changed Policy Bot from a credential-gated suspended Deployment to one desired
  replica after the GitHub App SSM placeholders were replaced and the rendered
  private key validated.
- Updated the Policy Bot runbook and knowledge-base notes so future credential
  rebuilds scale the app back to zero in git before reintroducing placeholders.

### 2026-05-25 - Add OpenClaw Discord and Codex setup notes

- Added `/homelab/openclaw/discord-bot-token` to the SSM contract and
  `openclaw-secrets` so OpenClaw can receive `DISCORD_BOT_TOKEN`.
- Changed OpenClaw startup bootstrap to let OpenClaw enable Discord from the
  environment when the SSM value has been replaced.
- Documented that ChatGPT Pro access should be configured through interactive
  OpenAI Codex OAuth on the OpenClaw PVC, not through committed API keys or SSM
  values.

### 2026-05-25 - Publish Terragrunt plan output to PR descriptions

- Rendered saved `plan.out` files from the trusted PR Terragrunt plan workflow
  into a managed pull request description section.
- Added a PR body updater that replaces the existing managed section after
  each successful plan so the description follows the latest plan output.
- Documented the new `pull-requests: write` permission on the trusted plan job
  and the local `TERRAGRUNT_PLAN_MARKDOWN` output path for reviewing rendered
  plans.

### 2026-05-25 - Refresh Image Updater GitHub App credentials

- Kept `argocd-image-updater-git` on `refreshPolicy: OnChange` and bumped the
  non-secret GitHub App SSM version marker to `2` so External Secrets refreshes
  the in-cluster write-back Secret from updated AWS SSM values.

### 2026-05-25 - Enable Image Updater pull requests

- Replaced the annotation opt-in ImageUpdater policy with a managed-image
  policy for every image declared directly in workload values or raw manifests.
- Added the `argocd-image-updater-git` ExternalSecret and SSM parameter
  contract for GitHub App credentials used by Git write-back pull requests.
- Updated validation and static checks so ImageUpdater-managed write-back
  targets may move tags through PRs while unmanaged image fields remain
  digest-pinned.

### 2026-05-25 - Stabilize firing workload alerts

- Suspended Policy Bot at zero replicas until its GitHub-App-owned SSM
  placeholders are replaced, preventing placeholder config from crashlooping.
- Changed n8n to use the SSM encryption key only for first-boot bootstrap and
  preserve the persisted PVC settings key on existing or restored instances.
- Tightened the static image digest gate so Argo Image Updater
  `manifestTargets` paths named `tag` are not treated as runnable container
  image tags.
- Updated workload and secret-contract notes so future alert repairs do not
  rotate persisted app keys or start apps with placeholder credentials.

### 2026-05-25 - Harden Terragrunt CI plan/apply phases

- Updated the Terragrunt PR plan workflow to skip privileged SSM declaration
  and Kubernetes secret materialization stacks, then run Argo CD Application
  registration plans serially with source refresh.
- Updated the protected apply workflow to use an environment-provided AWS apply
  role, expose Microsoft Entra provider credentials for Grafana SSO, and apply
  live Terragrunt phases explicitly instead of one parallel `IaC/live` sweep.
- Documented the OpenTofu state KMS permissions required by the production apply
  role and the split between automatic PR plans and protected apply checks.

### 2026-05-25 - Grafana Discord alert routing

- Populated the Grafana Discord webhook SSM parameter outside git and recorded
  the repo-owned rollout marker needed for Grafana to reload file-provisioned
  contact points.
- Changed `grafana-discord-webhook` to refresh from AWS SSM every five minutes
  so future webhook rotations update the Kubernetes Secret before the Grafana
  pod is rolled.

### 2026-05-25 - Initial knowledge base

- Added this Obsidian vault under `docs/knowledge-base`.
- Seeded notes for cluster topology, GitOps flow, storage, secrets, validation,
  workload inventory, and build patterns.
- Added the `homelab-knowledge-base` project skill so future agents read and
  update these notes during substantive work.

### 2026-05-25 - Import runbooks into Obsidian

- Added Obsidian runbook notes for onboarding, Argo CD bootstrap, app
  onboarding, image automation, CI/CD, tailnet ingress, rollback, runtime
  isolation, secrets, storage, Talos maintenance, and validation.
- Added app-specific operational notes from workload and platform READMEs.
- Added a source map so vault readers can jump back to canonical repo docs.
- Marked current working-tree app drift: Policy Bot and Hummingbot are present
  in source paths while Freqtrade is deleted and older inventory docs still need
  reconciliation.

### 2026-05-25 - Add Argo CD observability in Grafana

- Enabled Argo CD application controller, repo server, and API server metrics
  services in the bootstrap Helm values.
- Added Prometheus ServiceMonitors for those Argo CD metrics services under the
  monitoring app desired state.
- Added a repo-owned Argo CD Grafana dashboard and Grafana-managed alert rules
  for missing Argo CD metrics, unhealthy Applications, and Applications that
  remain out of sync.

### 2026-05-25 - Istio app service access policy

- Enabled Istio ambient labels for `ai`, `automation`, and `monitoring`.
- Added workload-scoped `AuthorizationPolicy` manifests for LiteLLM, OpenClaw,
  n8n, Grafana, Prometheus, Alertmanager, and kube-state-metrics.
- Recorded the current service-to-service access contract in
  `docs/runtime-isolation.md` and the workload inventory.
