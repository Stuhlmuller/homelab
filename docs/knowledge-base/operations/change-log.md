# Knowledge Base Change Log

Tags: #operations #knowledge-base

Record entries when a change creates, removes, renames, or materially changes an
app, platform dependency, workflow, topology assumption, secret contract,
storage requirement, or validation gate.

Use [[templates/knowledge-update]] for new entries.

## Entries

### 2026-05-25 - PR Conftest ordering

- Split Conftest policy evaluation out of `scripts/ci/static-checks.sh` into
  `scripts/ci/conftest-policies.sh`.
- Updated the pull request Terragrunt Plan workflow so trusted same-repository
  PRs run Conftest after the live Terragrunt plan step while forked PRs still
  run Conftest without receiving live-plan secrets.

### 2026-05-26 - Add Kiali mesh UI

- Added the `kiali` Argo CD Application and desired state using the official
  Kiali operator Helm chart.
- Exposed Kiali at `https://kiali.stinkyboi.com` through the tailnet-only Istio
  gateway with anonymous read-only access.
- Updated monitoring AuthorizationPolicies so Kiali can query Grafana and
  Prometheus without opening direct Prometheus ingress.

### 2026-05-25 - Add Hummingbot tailnet status route

- Added a tailnet-only Istio route at `https://hummingbot.stinkyboi.com` backed
  by a `route-status` sidecar on the Hummingbot pod.
- Kept interactive trading access on `kubectl attach`; the route is not the
  Hummingbot API and does not expose exchange credentials or trading controls.
- Added a repo-owned `finance` namespace manifest with baseline Pod Security
  labels and recorded the route in ingress, runtime-isolation, image-updater,
  and workload notes.

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
