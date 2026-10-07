---
type: workload
title: "Application Notes"
description: "Shared workload access and ownership rules, app-specific failure context, OpenClaw state, and Zimaboard resource constraints."
tags: ["workloads", "apps", "platform"]
---

# Application Notes

Canonical sources:

- [`clusters/homelab/apps/README.md`](../../clusters/homelab/apps/README.md)
- `clusters/homelab/apps/*/README.md`
- `clusters/homelab/platform/*/README.md`
- [Workload Inventory](inventory.md) for ownership, namespaces, dependencies, and state

## Shared Rules

Application desired state lives under `clusters/homelab/apps/<app>`; shared
platform state lives under `clusters/homelab/platform/<service>`. Register both
through `IaC/live/argocd-apps/<name>` and deliver runtime changes through Argo
CD rather than direct cluster mutation.

Human application access normally uses Octelium clientless `WEB` Services.
AFFiNE and Harbor use anonymous Octelium transport and delegate authentication
to the application. Both disable public signup; Harbor passes native OCI
Authorization headers and keeps its `homelab` project private.
NOFX requires Octelium human browser authentication before its own login.
Reviewed callback hosts use the public Octelium tunnel with explicit path
restrictions.
Tailscale is secondary LAN and egress infrastructure, not the primary app
access plane. `cloudflared` loads its mounted hostname map only at pod startup,
so every `octelium-public/configmap.yaml` routing change must also advance the
Deployment's `homelab.rst.io/cloudflared-config-revision` annotation. Without
that rollout trigger, a new public hostname reaches the tunnel but falls through
to the edge HTTP 404.

Persistent state, migration, backup, and restore behavior belong in each
workload README and [Storage And State](../architecture/storage-and-state.md). Secret values stay
outside git; repository-owned SSM paths and ExternalSecret contracts are
tracked in [Secrets And Identity](../architecture/secrets-and-identity.md).

## Kiali mesh visibility

The 2026-09-05 read-only probes found cluster-wide namespace and Istio config
listing working, but zero graph connections and no `istio_*` Prometheus series.
Kiali's API reported a startup Prometheus reachability failure retained in
memory, even though its CR enabled Prometheus. Upstream v2.26.0
`cmd/server.go` installs a permanent no-op client in that case.

`clusters/homelab/apps/kiali/values.yaml` waits for Prometheus readiness before
Kiali starts. `clusters/homelab/apps/prometheus/istio-podmonitors.yaml` owns
ztunnel L4, Envoy and Istiod scrape discovery. See the Kiali README for the
operator security flags, rollback and UI namespace selection. Validate rollout
with `python3 scripts/kiali-check.py`; Argo CD health alone is insufficient.
Live recovery remains unverified until the GitOps change rolls out. Grafana's
frontend-settings endpoint also returned 401; dashboard integration is a separate
follow-up requiring its existing authentication contract to be checked.

## Dispatcharr

Dispatcharr runs in upstream modular mode in the `media` namespace and exposes
`https://dispatcharr.stinkyboi.com` through the Octelium app access plane. Its
`data` PVC stores uploads and file-backed runtime data; accounts, including the
first administrator, and database configuration live in the dedicated
`dispatcharr-postgres` StatefulSet and PVC. Do not switch it to upstream
all-in-one mode on `nfs-default`: that image recursively changes ownership
below `/data/db`, which conflicts with the
QNAP export's squashed UID behavior. The web container uses upstream
`PUID`/`PGID` `65534` so nginx and Django match the export's anonymous owner.
The 2026-08-27 rollout produced ready web/database workloads while the protected
hostname returned `503`. On September 6, Octelium Entra login reached
Dispatcharr `0.29.0` on pinned image `df768adc…`; its first-run UI refused setup
for the forwarded public client IP. An authenticated Kubernetes port-forward
bound to `127.0.0.1` returned `superuser_exists: false` and `setup_allowed: true`
from the read-only setup endpoint. No POST or account creation was performed
during that inspection.

The user confirmed Dispatcharr was never configured. Read-only PostgreSQL
inspection found no accounts/admins, channels or streams, and only the default
custom M3U seed without a configured provider URL, file,
username or password, consistent with first-run state. Preserve both existing
data and PostgreSQL claims during setup. Transport and Octelium authentication
are verified; first-admin/provider setup and functional acceptance remain open.
Follow the loopback-only human setup procedure in
`clusters/homelab/apps/dispatcharr/README.md`; do not broaden
public setup access or create an administrator through a shell command.
Provider credentials, playlist URLs, and guide source secrets stay outside git.

On October 6, 2026 at 05:40 UTC, read-only inspection confirmed the Deployment and
PostgreSQL StatefulSet remain at zero replicas, both PVCs are `Bound`, and
Argo CD reports `Synced/Healthy`; that health does not establish playback.
The unchanged app requests 1664 MiB and can currently fit only on `acer`.
Placing it and its 256 MiB database there would leave about 1552 MiB of requested
memory headroom. Recheck capacity before resuming; stream/transcode peaks remain
untested. October 6 read-only checks located Plex and Jellyfin on QNAP
`10.1.0.2`: Plex responds on port `32400`; Jellyfin was deliberately disabled
and port `8096` is unavailable. The NAS cannot reach cluster Service IPs, and
the protected Dispatcharr hostname returns `401` without browser login.
An unattended private tuner route remains necessary; see
[QNAP Plex recovery](../operations/plex-recovery-2026-10-05.md) for the NAS service state.
The workload README now records M3U/XMLTV for Jellyfin and HDHR/XMLTV for Plex,
including private routing, profile selection and real-client acceptance.
The owner then selected the public IPTV-org USA M3U feed. The manifests now
restore one app/database replica, retain both claims and start PostgreSQL first.
The README records native account setup, daily stream refresh, manual bulk
channel creation and source rollback. Auto Channel Sync stays off for this
regular lineup to preserve control of guide mappings and failover streams.
The source has no embedded XMLTV URL, so guide setup remains
open. Runtime resumption and source/playback acceptance must be verified after
merge; the initial inspection alone changed no live state.

The resume render passed 560 policy checks, the full policy gate passed 25,704,
and the server-side dry-run accepted the existing workload shapes. That dry-run
also reported pre-existing restricted Pod Security warnings for the web, Celery
and Redis containers (root/privilege/capability/seccomp defaults). Source:
`clusters/homelab/apps/dispatcharr/values.yaml`. Review per-container hardening
against the upstream root startup wrapper before changing those defaults; no
namespace policy or runtime security settings were relaxed for resumption.

PR #1200 merged as `626a720f` on October 6, 2026 UTC. At 05:59 UTC, Argo CD
observed that revision and reported `Synced/Healthy` with a successful operation.
PostgreSQL was Ready on `zimaboard-1`; all three app containers were Ready on
`acer` without restarts, and both 20 GiB PVCs remained `Bound`. The running UI
reports Dispatcharr `0.31.0`. The loopback setup GET still returned
`superuser_exists: false` and `setup_allowed: true`; the first-administrator
form was opened for the operator. No account or source was created. IPTV-org
import, channel exports and playback remained pending that setup, followed by
private NAS routing and media-server acceptance.

On October 6, 2026 PDT, the operator created the first administrator privately.
Native UI setup added `IPTV-org USA` using the public USA M3U, Standard type,
24-hour refresh and no provider stream limit. All 74 discovered group cards
were enabled with Auto Channel Sync off. The refresh imported 1,451 streams;
manual sequential channel creation produced 1,451 Channels. `/output/m3u` and
`/hdhr/lineup.json` each returned HTTP 200 and 1,451 entries. CBS Sports Golazo
preview advanced with decoded 1920x1080 video; its exported MPEG-TS endpoint
returned 100 valid consecutive packet sync bytes. The sample establishes
Dispatcharr playback, not availability of every listed feed or media-server
acceptance. No external guide source was supplied. A subsequent native `Sports`
profile includes 65 channels across the five sports-tagged groups. Its HDHR
lineup has 65 entries; native XMLTV provides 1,170 placeholder programmes rather
than event schedules. No credentials were recorded.

The NAS media route is declared in `dispatcharr/values.yaml`: the existing nginx
adds listener `9192`, with a checksum-tracked ConfigMap and no extra container.
NodePort `31991` preserves source IP through `externalTrafficPolicy: Local`;
the app is pinned to its current `acer` node so `10.1.0.199:31991` stays stable.
Nginx permits only QNAP `10.1.0.2`, GET/HEAD and bounded M3U/XMLTV, HDHR,
stream-UUID and logo-cache paths. It rejects arbitrary queries and overwrites
forwarded headers; administrative access remains behind Octelium. This avoids
relying on unenforced NetworkPolicies or exposing the app's full `9191` port.
The endpoint has no failover while `acer` is unavailable. Route rollout and
Plex/Jellyfin playback remain acceptance gates; Jellyfin remains deliberately
stopped until the operator requests otherwise. See the workload README for
the test and rollback path.

Generated or adopted upstream resources must still have one declared owner.
Keep package capture and bootstrap commands in the workload README, and keep
steady-state resources under Argo CD wherever the upstream lifecycle permits.

## OpenClaw

The `2026.9.5` upgrade pins the external Codex and Discord plugins to the gateway
release and creates a new verified `pre-2026.9.5` archive. Keep the earlier
local-storage migration checkpoint. The pinned container's configuration and
plugin schemas, managed one-hour timeout, and compiled subscription-recovery
exports were checked; account-backed Discord/OpenRouter and scheduler acceptance
remain post-sync checks. See the app README for state-aware rollback.

On September 27, the upgraded gateway entered a 47-restart loop: it bound HTTP
after 87 seconds but remained event-loop-blocked while starting Discord, so the
two-minute startup probe terminated it before startup settled. The startup
budget is now six minutes; readiness still removes an unresponsive pod quickly,
and the existing six-minute liveness budget still bounds a later hang.
The recovered pod then exceeded its `6Gi` aggregate ephemeral-storage limit and
was evicted. Desired state now requests `8Gi` and limits `10Gi`; the worker had
about `17Gi` free and no disk pressure when measured. The backup CronJob now
shares sync wave `0` with the Deployment so Argo applies it before waiting on
the long rollout.

[OpenClaw Runtime State](../operations/openclaw-runtime-state.md) records runtime storage and recovery
requirements; [OpenClaw bootstrap batching](../operations/openclaw-bootstrap-batching.md) tracks startup costs.

Claw's reviewed assistant bundle lives in
`clusters/homelab/apps/openclaw/assistant/`: the OpenRouter free router, managed
personality/tool/operating notes, quiet follow-through heartbeats, a Pacific
09:00 briefing, twice-hourly daytime health watch, and one bounded daily
improvement session. Stable automation declaration keys preserve history and
operator pauses. Reconciliation preserves unrelated security, memory, and
research routines.
The existing allowlisted owner supplies the Discord DM route;
ambiguous routing defers scheduling without breaking gateway startup. Verify
`assistant-reconciliation.json` reports `ready` as well as Pod readiness.
Bootstrap retains original files privately and
preserves personal memory. The Pod annotation hashes the full bundle so GitOps
changes take effect on restart. See the app README for validation and rollback;
configured `openrouter/free` is not proof of account access until a real turn
succeeds. Astra via Codex OAuth remains an operator-selected recovery route.

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

Use [Workload Inventory](inventory.md) as the current cross-workload summary and read the named
source README before changing an application.

The September 6 [Deluge CPU Audit — 2026-09-05](../operations/deluge-cpu-audit-2026-09-05.md) isolates Gluetun's
sustained 300m use mostly to its main process while VPN and RPC health remain
good. Its disabled file-configured loopback profiler and bounded private
capture helper support diagnosis before changing the cap. Current saturation
must be revalidated before activation. Activation and
removal require separate reviewed Recreate rollouts; live profiling is unverified.

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

Grafana persists provisioned alerts in its PVC-backed database. Retiring a
rule requires `deleteRules` in `clusters/homelab/apps/grafana/values.yaml` and
an alerting provisioning version bump; removing it from `groups` alone does
not delete the existing rule. The retired Octelium UPnP rule uses this path.

[Monitoring Resource Requests](../operations/monitoring-resource-requests.md) records the September 2026
memory measurements, explicit monitoring reservations, scheduling-fit model,
and required post-rollout checks. These requests protect scheduler accounting;
the cluster's remaining failover-capacity deficit remains open.

## Sonarr

Sonarr runs behind Octelium with `AuthenticationMethod=External` and
`AuthenticationRequired=DisabledForLocalAddresses`. Its startup path mirrors the
Radarr auth recovery pattern: active config is on `sonarr-config-local` on
`zimaboard-0`; init containers normalize the local `config.xml`, remove legacy
auth tags, and pass matching `SONARR__AUTH__*` environment settings while the
linuxserver default config init script stays disabled. The validated one-time
NFS migration resources are removed. Keep the legacy NFS claim as the nightly
archive and rollback target; only the backup CronJob mounts it.


## Bazarr

[Bazarr's runbook](../../clusters/homelab/apps/bazarr/README.md) owns the
English subtitle policy, Sonarr/Radarr bootstrap, provider setup, and acceptance
checks. Both media roots match their source applications, so no path mapping is
needed. The app shares `zimaboard-0` with the local source config claims; its
resource reservations need validation against live library scans.

The first rollout on 2026-10-05 confirmed the same
[Talos subPath mount boundary](../operations/openclaw-runtime-state.md#direct-mount-identity)
seen with OpenClaw: host and Arr pods had regular XML files, but kubelet's
isolated overlay exposed directories at those paths. Bazarr now mounts the
whole source config claims read-only in its configure init container, with no
source mounts in the main container. No host config or permissions repair is
needed for this failure.

Its UI at `https://bazarr.stinkyboi.com` is a public Octelium WEB Service using
the existing human-only policy, with anonymous access disabled.
The guarded `scripts/octelium-bazarr-reconcile.py` helper reconciles only that
catalog Service from a clean checkout at reviewed current `main`. Publish its
digest through the existing exact-main `harbor-mirror.yml`
`image_scope=bazarr` path before application registration, because Talos disables
upstream fallback. The PostSync initial-backup hook proves the first archive
after configuration; nightly backups follow at 04:45 Pacific. The separate
`finish-setup` command waits for import and search completion outside Argo's sync
timeout. Verify
an actual downloaded sidecar subtitle before treating a healthy pod as completed
subtitle setup.

Initial backup acceptance on 2026-10-05 found finalized archives followed by
`OSError` and leftover temporary directories on NFS. The helper's SQLite
transaction contexts left both connections open at directory cleanup, confirmed
by a regression test. Explicit connection closure now precedes archiving and
cleanup. Open-file NFS cleanup failure fits the live evidence; the original
errno was not retained. Require a successful hook with a verified archive
before considering backup acceptance complete.
