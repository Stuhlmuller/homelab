# Application Notes

Tags: #workloads #apps #platform

Canonical sources:

- [`clusters/homelab/apps/README.md`](../../../clusters/homelab/apps/README.md)
- `clusters/homelab/apps/*/README.md`
- `clusters/homelab/platform/*/README.md`
- [[inventory]] for ownership, namespaces, dependencies, and state

## Shared Rules

Application desired state lives under `clusters/homelab/apps/<app>`; shared
platform state lives under `clusters/homelab/platform/<service>`. Register both
through `IaC/live/argocd-apps/<name>` and deliver runtime changes through Argo
CD rather than direct cluster mutation.

Human application access normally uses Octelium clientless `WEB` Services.
AFFiNE and NOFX are reviewed exceptions: their Octelium Services are anonymous
and delegate login to the applications. AFFiNE public signup remains disabled.
Reviewed callback hosts use the public Octelium tunnel with explicit path
restrictions.
Tailscale is secondary LAN and egress infrastructure, not the primary app
access plane. `cloudflared` loads its mounted hostname map only at pod startup,
so every `octelium-public/configmap.yaml` routing change must also advance the
Deployment's `homelab.rst.io/cloudflared-config-revision` annotation. Without
that rollout trigger, a new public hostname reaches the tunnel but falls through
to the edge HTTP 404.

Persistent state, migration, backup, and restore behavior belong in each
workload README and [[../architecture/storage-and-state]]. Secret values stay
outside git; repository-owned SSM paths and ExternalSecret contracts are
tracked in [[../architecture/secrets-and-identity]].

## Dispatcharr

Dispatcharr runs in upstream modular mode in the `media` namespace and exposes
`https://dispatcharr.stinkyboi.com` through the Octelium app access plane. Its
`data` PVC stores file-backed runtime data and operator-configured IPTV sources,
while database state lives in the dedicated `dispatcharr-postgres` StatefulSet
and PVC. Do not switch it to upstream all-in-one mode on `nfs-default`: that
image recursively changes ownership below `/data/db`, which conflicts with the
QNAP export's squashed UID behavior. The web container uses upstream
`PUID`/`PGID` `65534` so nginx and Django match the export's anonymous owner.
The 2026-08-27 rollout then produced a ready three-container web Pod and ready
PostgreSQL StatefulSet. Internal HTTP returns `200`, but the Octelium-protected
hostname still returns `503`; public access validation remains open.
Provider credentials, playlist URLs, and guide source secrets stay outside git.

Generated or adopted upstream resources must still have one declared owner.
Keep package capture and bootstrap commands in the workload README, and keep
steady-state resources under Argo CD wherever the upstream lifecycle permits.

## OpenClaw

OpenClaw persists runtime state on the `openclaw` PVC under `/data/openclaw`.
The `operator-toolbox` init container installs the operator command set with
Nix, then shares both `/toolbox/profile` and `/nix` with the app and bootstrap
containers. Keep the copied Nix database and shared store as a matched unit:
copying only the profile runtime closure while copying the full database leaves
missing `.drv` entries, and fresh agent shells fail when `nix develop` evaluates
the homelab flake.

## Zimaboard-0 Resource Envelope

A seven-day Prometheus review on 2026-08-26 found that scheduling requests did
not describe the work pinned to `zimaboard-0`. Deluge's `port-config` helper
used about `905m` CPU at p95 while retrying a console-output false negative
every two seconds, and `daemon-metrics` used about `296m` because every scrape
spawned `deluge-console`. The Deluge app itself measured `437m` CPU and `213Mi`
memory at p95. Prowlarr, Radarr, and Sonarr stayed below `24m` CPU p95 but each
needed roughly `134-171Mi` memory. OpenClaw measured about `995m` CPU and
`1.8Gi` memory at p95. Multiple app pod series exceeded `4Gi`, maxima approached
`6Gi`, and three containers terminated as OOMKilled.

Desired state now bounds every long-running container. Deluge verifies typed
`core.conf` values, backs failed startup reconciliation off to 60 seconds,
rechecks every five minutes, and refreshes cached health metrics once per
minute. OpenClaw caps init and app CPU bursts and cannot schedule on an Octelium
dataplane node. Its `4Gi` app limit deliberately trades an app OOM for worker
health after a 2026-08-28 rise to `5.36Gi` immediately preceded loss of the
8 GiB worker. The three Servarr apps have explicit requests and limits.
Re-measure after 48 hours of healthy runtime before raising a limit or relaxing
affinity.

Use [[inventory]] as the current cross-workload summary and read the named
source README before changing an application.

## Prometheus

Prometheus owns the durable notification path from in-cluster alert rules to
Alertmanager, Discord, and OpenClaw. It selects repo-owned `ServiceMonitor`
objects and repo-owned `PrometheusRule` objects in the `monitoring` namespace
without requiring Helm release labels, so cross-workload alert coverage can
live beside the responsible application manifests.

Argo CD application health and sync alerting has a Prometheus-native safety
net in `clusters/homelab/apps/prometheus/argocd-prometheusrules.yaml`. Keep
that rule file aligned with the Grafana-managed Argo CD alerts, but do not
depend on Grafana rule evaluation for the only Argo CD notification path. After
rollout, validate that the `argocd-application-health` `PrometheusRule` is
present and that Prometheus is receiving `argocd_app_info`.

## Sonarr

Sonarr runs behind Octelium with `AuthenticationMethod=External` and
`AuthenticationRequired=DisabledForLocalAddresses`. Its startup path mirrors the
Radarr auth recovery pattern: active config is on `sonarr-config-local` on
`zimaboard-0`; init containers normalize the local `config.xml`, remove legacy
auth tags, and pass matching `SONARR__AUTH__*` environment settings while the
linuxserver default config init script stays disabled. The validated one-time
NFS migration resources are removed. Keep the legacy NFS claim as the nightly
archive and rollback target; only the backup CronJob mounts it.
