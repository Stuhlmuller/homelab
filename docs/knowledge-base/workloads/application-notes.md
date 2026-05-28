# Application Notes

Tags: #workloads #apps #platform

Sources:

- `clusters/homelab/apps/README.md`
- `clusters/homelab/apps/*/README.md`
- `clusters/homelab/platform/*/README.md`

## Shared App Rules

App desired state lives under `clusters/homelab/apps/<app>`. Typical files are
Helm values, ExternalSecret references, VirtualServices, Kustomize resources,
and app-specific README notes. No file in this tree may contain secret values,
private keys, raw certificate material, private kubeconfigs, or private
hostnames.

Most routes are tailnet-only. Public Funnel is limited to reviewed webhook
exceptions such as Policy Bot's `/api/github/hook`.

## Platform DNS

`platform-dns` owns the CoreDNS `ConfigMap` in `kube-system`. It forwards
external lookups to `1.1.1.3` and `1.0.0.3` so controllers do not inherit an
unstable node-local upstream. Do not manually patch live CoreDNS; change the
repo overlay and Application registration.

## Platform Storage

`platform-storage` owns the QNAP-backed NFS dynamic provisioner and the default
`nfs-default` StorageClass. Do not depend on stateful workloads until the
provisioner is healthy and the PVC smoke test in [[../runbooks/storage-nfs]]
has passed.

## Argo CD Image Updater

The cluster-local `homelab-managed-images` ImageUpdater manages repo-declared
workload images from a central CR and opens GitHub pull requests through Git
write-back. The `argocd-image-updater-git` ExternalSecret must resolve before
updates can be pushed.

## Deluge

Deluge is coupled to Gluetun. If VPN secrets are missing, WireGuard config is
bad, or Gluetun is unhealthy, Deluge must not become ready. The app owns the
shared `media-downloads` PVC backed by the QNAP `/media` export and used by
Radarr and Sonarr at `/downloads`. The `media-downloads-migration` Job copies
the older `deluge-downloads` PVC into `/media/downloads` and verifies write
access before cutover.

## Grafana

Grafana is the reviewed metrics UI. It uses Microsoft Entra SSO from
`IaC/live/azuread-applications/grafana`, provisions Prometheus and Alertmanager
datasources, Homelab and Argo CD dashboards, and Grafana-managed alerts from
repo-owned values. Discord webhook URL comes from SSM through External Secrets.

## Kiali

Kiali is the reviewed read-only Istio mesh UI at
`https://kiali.stinkyboi.com`. The `kiali` Argo CD Application installs the
official Kiali operator chart and creates a Kiali CR in `monitoring` with
anonymous access plus `view_only_mode: true`. Monitoring AuthorizationPolicies
allow `kiali-service-account` to query Grafana and Prometheus.

## OctoBot

OctoBot is the finance namespace trading bot with a real web UI. It runs from
the upstream `drakkarsoftware/octobot` image, listens on container port `5001`,
and exposes only the tailnet Istio route at `https://octobot.stinkyboi.com`.
State persists on the `octobot-user`, `octobot-tentacles`, and `octobot-logs`
PVCs using `nfs-default`.

```sh
kubectl -n finance get deploy,pod,pvc,svc -l app.kubernetes.io/instance=octobot
curl -I https://octobot.stinkyboi.com
```

Do not add exchange API credentials, live-trading autostart, or strategy config
to git. First-run setup, tentacles, strategy state, and exchange credentials
are configured through the UI and stored on the PVCs. Start with paper trading;
before enabling live trading, document backtest and paper-trading evidence and
confirm withdrawal access is disabled at the exchange.

The older Hummingbot workload is retired in place. Its Argo CD Application now
keeps only the `hummingbot-*` PVCs so Argo can prune the old workload resources
without deleting rollback data. The old `/homelab/hummingbot/config-password`
SSM parameter remains declared until those PVCs are archived or removed.

## OpenClaw

OpenClaw persists runtime state on `/data/openclaw`. The startup bootstrap
keeps the tailnet Control UI origin allow-list in config and stores
`gateway.auth.token` as an environment-backed SecretRef to
`OPENCLAW_GATEWAY_TOKEN`, sourced from the generated
`/homelab/openclaw/app-secret` SSM parameter. When
`/homelab/openclaw/discord-bot-token` has been replaced in SSM, bootstrap
installs and enables the official `@openclaw/discord` plugin and writes a
SecretRef to `DISCORD_BOT_TOKEN`. The plugin npm cache and extension directory
are `emptyDir` mounts at `/data/openclaw/npm` and
`/data/openclaw/extensions` because QNAP NFS maps PVC writes to `nobody`, and
OpenClaw blocks code plugins with suspicious ownership. ChatGPT Pro access uses
interactive OpenAI Codex OAuth stored on the PVC; do not model that as an SSM
secret or committed API key. The bootstrap also enables the bundled `codex`
plugin and sets the default agent model to `openai/gpt-5.5`, which is the
canonical Codex-backed OpenAI model route for new OpenClaw config. The
bootstrap enables the bundled `memory-wiki` plugin so Imported Insights and
Memory Palace are available after the Control UI tab is reloaded. The
bootstrap runs safe `openclaw doctor --fix --non-interactive` repairs when the
persisted PVC config does not validate against the current OpenClaw schema, and
sets `gateway.mode` to `local` for the container-managed gateway process.
GitHub App identity is SSM-backed: `GITHUB_APP_ID` and
`GITHUB_APP_INSTALLATION_ID` come from `openclaw-secrets`, while the private key
is mounted from `openclaw-github-app-private-key` and referenced by
`GITHUB_APP_PRIVATE_KEY_PATH` at
`/var/run/secrets/openclaw/github-app/private-key.pem`.
OpenClaw has an explicit agent-heavy resource profile: the app requests `1`
CPU and `2Gi` memory with a `6Gi` memory cap and no CPU limit, while bootstrap
gets enough memory to validate config and install channel plugins at startup.

## Media PostgreSQL

`media-postgres` is the shared PostgreSQL 14 instance for Sonarr, Radarr, and
Prowlarr. It exposes only
`media-postgres.media.svc.cluster.local:5432`, persists on `nfs-default`, and
creates six logical databases:

- `sonarr-main`
- `sonarr-log`
- `radarr-main`
- `radarr-log`
- `prowlarr-main`
- `prowlarr-log`

Application-ready restore requires logical dumps plus matching app config PVC
backups.

## n8n

n8n persists `/home/node/.n8n` on NFS. Its stable encryption key comes from
`/homelab/n8n/encryption-key` only on first boot. The pod receives it as
`N8N_BOOTSTRAP_ENCRYPTION_KEY` and exports `N8N_ENCRYPTION_KEY` only when the
persisted `/home/node/.n8n/config` file is absent, so restored or existing PVCs
continue using their persisted instance key. Do not rotate the SSM value as a
shortcut for changing an existing n8n instance key.

## Policy Bot

Policy Bot is an in-flight stateless automation workload. The tailnet UI lives
at `https://policy-bot.stinkyboi.com/details/<org>/<repo>/<pull-request>`.
The public GitHub webhook is:

```text
https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook
```

Root routes stay unrouted. The public route depends on Tailscale Funnel for
`tag:k8s` and Policy Bot's own webhook HMAC validation.

The Deployment runs one replica after the GitHub App ID, private key, OAuth
client ID, and OAuth client secret placeholders are replaced in SSM. Scale it
back to zero in git before reintroducing placeholder config.

Policy Bot's `integration_id` field is the GitHub App ID from the app's general
settings page, not the installation ID or OAuth client ID. A startup log with
`failed to get configured GitHub app` and `404 Integration not found` from
`https://api.github.com/app` means the rendered app ID and private key do not
identify the same active GitHub App. The ExternalSecret uses
`refreshPolicy: OnChange`, so SSM fixes need a repo-owned metadata change and
Argo CD sync before the rendered Kubernetes Secret changes.

## Prometheus

Prometheus persists metrics and Alertmanager state on `nfs-default`.
Prometheus is intentionally not exposed through tailnet ingress; Grafana is the
operator UI. It also owns ServiceMonitors for the Argo CD application
controller, repo server, and API server metrics services. Re-enable Talos
component metrics only after adding matching Talos machine-config patches and
proving targets are `up`.

## Prowlarr, Radarr, And Sonarr

The Servarr apps use `media-postgres` and configure PostgreSQL through
persistent `/config/config.xml` fields instead of environment overrides. The
desired state does not migrate existing SQLite data; follow upstream migration
guides before treating a migration rollout as complete.

Radarr and Sonarr keep `/config` and PostgreSQL state on `nfs-default`, but
their library mounts now target the QNAP `/media` export: Radarr uses
`media-movies` at `/movies`, Sonarr uses `media-tv` at `/tv`, and both share
`media-downloads` at `/downloads`. The old dynamic media PVCs stay declared as
migration sources until the `/media` copy is verified.

## Tailscale

The Tailscale app owns operator support resources, the privileged `tailscale`
namespace, the `operator-oauth` ExternalSecret, and the `homelab-exit-node`
Connector. Tailnet policy must allow `tag:k8s-operator` to own `tag:k8s` and
auto-approve exit-node advertisement when possible.
