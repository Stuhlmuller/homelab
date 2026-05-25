# Knowledge Base Change Log

Tags: #operations #knowledge-base

Record entries when a change creates, removes, renames, or materially changes an
app, platform dependency, workflow, topology assumption, secret contract,
storage requirement, or validation gate.

Use [[templates/knowledge-update]] for new entries.

## Entries

### 2026-05-25 - Enable Policy Bot replica

- Changed Policy Bot from a credential-gated suspended Deployment to one desired
  replica after the GitHub App SSM placeholders were replaced and the rendered
  private key validated.
- Updated the Policy Bot runbook and knowledge-base notes so future credential
  rebuilds scale the app back to zero in git before reintroducing placeholders.

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
