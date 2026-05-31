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
exceptions such as n8n's webhook prefixes and Policy Bot's `/api/github/hook`.

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
access before cutover. `deluge-vpn` reads a full AirVPN `wg0.conf` from
`/homelab/deluge/vpn/wireguard-config` so Gluetun uses the selected peer
instead of a random provider endpoint. AirVPN profile rotations require
updating that SSM value and bumping
`homelab.rst.io/wireguard-profile-ssm-version` on both the `deluge-vpn`
ExternalSecret and Deluge pod template so External Secrets rereads SSM and
Gluetun restarts with the new profile. The pod resolves endpoint DNS names in
the profile to IPv4 before Gluetun starts. Keep Deluge's AirVPN forwarded port
fixed only for `listen_ports`; `outgoing_ports` should stay at Deluge's default
random behavior, otherwise active torrents can report too few outgoing ports
and fail to establish enough peer connections.

## Grafana

Grafana is the reviewed metrics UI. It uses Microsoft Entra SSO from
`IaC/live/azuread-applications/grafana`, provisions Prometheus and Alertmanager
datasources, a public GitHub API Infinity datasource, Homelab, Argo CD, and
GitHub PR status dashboards, and Grafana-managed alerts from repo-owned values.
Discord webhook URL and the OpenClaw alert hook token come from SSM through
External Secrets. Grafana sends alert notifications both to Discord and
directly to OpenClaw's authenticated `/hooks/agent` endpoint.
Alerting-only provisioning changes bump
`homelab.rst.io/alerting-provisioning-version` so Grafana restarts and applies
rule additions, updates, and deletions.
The GitHub dashboard and Actions failure alerts use unauthenticated public REST
API reads against `Stuhlmuller/homelab`, so keep polling conservative unless a
token-backed secret contract is added.
Its Helm-rendered Deployment uses a resource-level Argo CD `Replace=true` sync
option because the app keeps a `Recreate` strategy for the single Grafana PVC,
and server-side apply can otherwise preserve stale `rollingUpdate` fields.

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

Image automation is pinned to `2.1.1` until a newer image is tested against the
current PVC-backed config. The `2.1.13` image rejected
`config.trading.paused` during startup migration and crash-looped.
Grafana has a generic critical alert for any Kubernetes pod container stuck in
`CrashLoopBackOff` for five minutes, so OctoBot crash loops should notify
Discord even when broader scrape-target or Argo CD health alerts do not fire.

```sh
kubectl -n finance get deploy,pod,pvc,svc -l app.kubernetes.io/instance=octobot
curl -I https://octobot.stinkyboi.com
```

Do not add exchange API credentials, live-trading autostart, or strategy config
to git. First-run setup, tentacles, strategy state, and exchange credentials
are configured through the UI and stored on the PVCs. Start with paper trading;
before enabling live trading, document backtest and paper-trading evidence and
confirm withdrawal access is disabled at the exchange.

The `retired-workload-cleanup` hook in the OctoBot app removes stale finance
PVCs from the retired trading runtime during Argo CD sync.

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
The Control UI error
`unauthorized: device token mismatch (rotate/reissue device token)` means the
browser's cached device-pairing token is stale against the gateway. Verify the
gateway with `openclaw gateway health`, identify the
`clientId: openclaw-control-ui` record with `openclaw devices list --json`, then
refresh the browser's site data or rotate the affected operator token with
`openclaw devices rotate --device <device-id> --role operator`. Any generated
device token or token-bearing dashboard URL is secret runtime material and must
stay out of git.
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

## n8n PostgreSQL

`n8n-postgres` is a dedicated PostgreSQL support app in the `automation`
namespace. It exposes only `n8n-postgres.automation.svc.cluster.local:5432`,
persists on `nfs-default`, and creates the `n8n` role/database from generated
SSM passwords at `/homelab/n8n/postgres-admin-password` and
`/homelab/n8n/postgres-app-password`. The admin password stays in
`n8n-postgres-auth`; n8n receives only the application password through
`n8n-postgres-client` and `DB_POSTGRESDB_PASSWORD_FILE`.

Changing database names, users, or passwords after first initialization needs
an explicit migration or `ALTER ROLE` plan because PostgreSQL init scripts only
run against an empty data directory.

## n8n

n8n uses `DB_TYPE=postgresdb` and waits for an authenticated connection to
`n8n-postgres` before startup. Workflows, users, credential metadata, and
execution history live in PostgreSQL. `/home/node/.n8n` still persists on NFS
for the instance config, encryption-key settings, and file-backed runtime data.

The stable encryption key comes from `/homelab/n8n/encryption-key` only on
first boot. The pod receives it as `N8N_BOOTSTRAP_ENCRYPTION_KEY` and exports
`N8N_ENCRYPTION_KEY` only when the persisted `/home/node/.n8n/config` file is
absent, so restored or existing PVCs continue using their persisted instance
key. Do not rotate the SSM value as a shortcut for changing an existing n8n
instance key.

The PostgreSQL desired state preserves the old SQLite file on the PVC but does
not automatically import rows from it. Export workflows and credentials before
rollout when existing SQLite contents must be preserved.

n8n keeps the editor and API on `https://n8n.stinkyboi.com`, but advertises
workflow webhook URLs through `https://n8n-webhook.tail67beb.ts.net`. The
Funnel route is limited to `/webhook`, `/webhook-test`, and
`/webhook-waiting`, and forwards through the Istio ingress gateway so the n8n
workload AuthorizationPolicy can continue allowing only the gateway service
account.

## Policy Bot

Policy Bot is an in-flight stateless automation workload. The tailnet UI lives
at `https://policy-bot.stinkyboi.com`, including the root page, details pages,
static assets, and OAuth callback.
The public GitHub webhook is:

```text
https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook
```

Only the webhook route is public. The public route depends on Tailscale Funnel
for `tag:k8s` and Policy Bot's own webhook HMAC validation.

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

Radarr uses `AuthenticationMethod=External` in `/config/config.xml`, managed by
the startup init container in `clusters/homelab/apps/radarr/values.yaml`. The
app is tailnet-only with Funnel disabled, so the tailnet gateway is the external
access boundary. This avoids recurring Radarr password lockouts from internal
auth drift. If Radarr is ever exposed beyond the tailnet, restore Forms auth or
add a forward-auth layer first.

## Tailscale

The Tailscale app owns operator support resources, the privileged `tailscale`
namespace, the `operator-oauth` ExternalSecret, and the `homelab-exit-node`
Connector. Tailnet policy must allow `tag:k8s-operator` to own `tag:k8s` and
auto-approve exit-node and `10.1.0.0/24` subnet-route advertisement when
possible.
