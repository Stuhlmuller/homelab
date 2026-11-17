# Implementation Plan: Homelab uptime monitoring

**Branch**: `codex/uptime-kuma` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

## Summary

Deploy Uptime Kuma 2.5.11 in `monitoring` using the existing app-template 4.4.0
and Kustomize pattern. Configure monitors through its pinned native Socket.IO
interface, using a small repository-owned Node adapter in the same image.
Use direct application health endpoints and built-in JSON-query monitors against
existing Prometheus workload signals. Keep an exhaustive app coverage catalog,
retained local SQLite, checked NFS backups and private native-authenticated UI.

## Technical Context

**Language/Version**: Node.js supplied by pinned Kuma image; Python 3 for offline
catalog checks and SQLite backup; YAML/JSON and Terragrunt HCL.

**Primary Dependencies**: Kuma 2.5.11, bundled socket.io-client ~4.8.3 and JSONata
2.2.0; app-template 4.4.0; existing Argo CD, Prometheus, Traefik/Tailscale,
External Secrets and shared generated SSM stack.

**Image**: `docker.io/louislam/uptime-kuma:2.5.11@sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9`.
Publish the complete multi-platform artifact to Harbor before consumption.
Helper images reuse exact existing catalog pins and undergo runtime module checks.

**Storage**: 5Gi retained local PV/PVC on `acer`, path `/var/lib/uptime-kuma`,
with single-writer `Recreate`; 5Gi retained `nfs-default` backup PVC. HostPath
capacity is not a quota. NFS is only the backup destination, never live SQLite.

**Testing**: adapter contract and fixture tests; actual pinned-image integration;
render/static/policy checks; protected IaC plan/apply tests; live revision,
coverage, three observations, safe failure/recovery and isolated restore proof.

**Target Platform**: existing amd64 Talos/Kubernetes cluster; `monitoring` is
already ambient-enrolled and allowed by the SSM store and `homelab` AppProject.

**Project Type**: new declarative homelab app plus bounded configuration adapter.

**Performance Goals**: 60-second continuous checks, timeout 10 seconds, at most
one retry; sustained failure/recovery within 180 seconds. Reconcile on startup
and every 300 seconds; interval does not alter check cadence. Keep 30 days.

**Constraints**: no runtime package installs, no new public route, no changes to
existing notification recipients, no ad hoc cluster mutations, no account reset,
no missing-data-as-healthy behavior. API compatibility is version-bound.

**Scale/Scope**: baseline union has 60 entries (55 repository app declarations,
56 live Applications, captured during plan), plus the new app. Inventory is an
app/service boundary, not every Pod. Recheck this union at implementation and
acceptance; do not silently drop added apps.

## Constitution Check

| Principle | Before research | After design |
| --- | --- | --- |
| Repository-owned desired state | Pass: all changes through source/declared workflows | Pass: manifests, catalog, adapter and fixed acceptance operations are code-owned |
| Public secret safety | Pass: references only | Pass: generated SSM password, file mounts, sanitized counts, no secret artifacts |
| Validation before live changes | Pass: research read-only | Pass: image publication, checks, saved-plan lane and live acceptance specified |
| Reviewable/teachable changes | Pass: issue/spec retained | Pass: app runbook, coverage and restore/rollback docs included |
| Bootstrap/ownership | Pass: existing stack retained | Pass: generated Application and existing SSM lane, no parallel infrastructure system |

No constitutional exception is required. The restore execution fence modifies
only an ephemeral clone after archive verification; it grants no production SQL
write or network-policy activation. Gate success here validates design,
not a deployment. Existing failed executable checks remain blockers to delivery.

## Project Structure

Feature artifacts: `spec.md`, `research.md`, `data-model.md`, `contracts/`,
`quickstart.md`, `checkpoint.md`; `tasks.md` is generated in its own later stage.

Source owners:

- `clusters/homelab/apps/uptime-kuma/`: values, local storage, backup claim,
  ExternalSecret, ConfigMap-packaged `reconcile.js`, `backup.py`, catalog,
  initial/periodic backup and isolated restore Jobs, network policies, README.
- `IaC/homelab/us-west-2/apps/uptime-kuma/{stack.hcl,terragrunt.stack.hcl}`:
  `monitoring` destination, existing `homelab` project (local PV/StorageClass
  require cluster resources), pinned multi-source chart and overlay.
- Shared SSM catalog: generated `/homelab/uptime-kuma/admin-password`, no
  plaintext default; username `admin` is nonsecret committed configuration.
- `scripts/ci/uptime-kuma-check.py` and `uptime-kuma-test.js`: catalog/schema,
  missing-coverage, adapter behavior and manifest boundary checks, wired into
  existing static-check entrypoints.
- Image catalog, fixed `uptime-kuma` mirror inventory, publisher scope and tests;
  targeted Terragrunt SSM preflight/apply lane and tests.
- Existing Traefik routes/hostname annotation, private DNS inventory, target
  AuthorizationPolicies and NetworkPolicies: exact new route/principal only.
- App onboarding table, OpenWiki inventory, storage/secret/validation notes:
  source-linked additions, no generated wiki artifacts.

## Runtime design

### Bootstrap and reconciliation

Use one app Pod with main Kuma and a reconciler sidecar; disable service-account
API-token automount. Only bootstrap/reconciler receive the admin secret mount.
Run bootstrap, main Kuma, reconciler, first/nightly backup and restore verification
as UID/GID 10001 with fsGroup 10001, dropped capabilities, no privilege escalation
and RuntimeDefault seccomp. The narrowly scoped root ownership init remains the
only exception: chown only the initial data mount root to 10001:10001 and chmod
0700, with only CHOWN/FOWNER capabilities; do not recursively migrate retained
state. This is a new undeployed workload, so no existing UID migration is implied.
Keep projected credential/config mounts readable by this group and scratch/clone
storage writable by this identity without broad permissions or policy suppression.
Require actual pinned-image integration at 10001:10001 for bootstrap, native API
and reconciliation, read-only live-WAL backup and fenced native restore; former
UID 1000 results do not establish this identity's runtime compatibility.
Initial requests: app 100m/256Mi, limits 1000m/1Gi; adapter 10m/64Mi, limits
200m/256Mi. Verify node resource headroom before registration.

An init container writes `db-config.json` containing `{"type":"sqlite"}` only
for a genuinely empty data directory, starts the pinned server with
`--host=127.0.0.1 --port=3001 --data-dir=/app/data`, completes `needSetup`/`setup`
only when necessary, logs in with mounted credentials, sets retention via
read/merge/write settings, then gracefully terminates and waits for the server.
Existing invalid configuration or failed login stops initialization; never
silently recreate data or reset an account. No application listener is reachable
through the Service until init succeeds. Preserve existing database config.

The main process starts only after that server exits. Main probes check its
local HTTP behavior with a startup grace period; readiness of the reconciler
also requires a successful first catalog reconciliation. The sidecar connects
only to localhost, subscribes before `getMonitorList`, uses bounded requests,
merges owned fields into full `getMonitor` objects and writes only changed
settings. Description markers identify stable keys; duplicates fail before
mutation. Retired entries pause, never delete. A sanitized status file gives
catalog hash, last-success time and counts; subsequent failures are visible in
logs/status without deleting last usable configuration. Reject multiple writers.

### Monitor catalog and coverage

`monitors.json` contains schema version, app entries and monitor definitions.
Classify each registered/live app as active, staged, suspended, retired or
configuration-only, with source evidence. Active entries require enabled direct
or shared monitor IDs; configuration-only entries name their owning/child
service coverage and cannot claim a synthetic runtime health endpoint.

Use HTTP/JSON health endpoints for browser apps where meaningful (Grafana,
LiteLLM, n8n, media apps, Langfuse, Fleet, NOFX, Multica, Harbor, Compass, Kiali,
Argo CD). Choose paths from each app's probes and pinned upstream semantics;
expected status/body and the check's limits are explicit. Do not accept generic
401/302 as health. For apps without a meaningful unauthenticated health path,
use their existing workload readiness signal rather than distributing app admin
credentials. Private access availability is independently checked during UI
acceptance; backend uptime is not claimed as end-to-end ingress uptime.

For controller/support apps and scheduled work, use native `json-query` monitors
against the internal Prometheus instant-query endpoint. Each query requires the
exact workload identity, healthy desired/available state, and source timestamp
age no greater than twice the actual configured observation/scrape period of
each required source (15-second scrape means a 30-second maximum age). Record
the period and its configuration source in the catalog; do not substitute the
60-second Kuma check cadence or a fixed 120-second allowance. Only explicitly
documented scheduled-work freshness thresholds are exceptions. A missing series,
stale source, zero desired replicas for an active app, unhealthy required
component, malformed JSON or non-single healthy result is down. Scheduled-work
success thresholds use committed schedules plus explicit tolerance; suspended
jobs are not treated as failed continuous servers. Reuse existing metrics and
per-workload predicates; no new Kubernetes inventory operator or broad API RBAC.

Start implementation from the plan's observed union and current app sources.
Stopped AFFiNE, legacy OpenClaw, Mastodon web, Bulldozer, Crossplane, nix-builder
and staged Enterprise/envoy/network-policy entries require current source-backed
dispositions. Do not assume all components of a partially stopped app are off:
Mastodon databases, for example, can remain active and need supporting coverage.
`live` and child provisioner Applications need explicit ownership classification.
Acceptance also reconciles current live names against the committed catalog.

### Network and access

Serve `https://uptime-kuma.stinkyboi.com` on Traefik's existing private
`websecure` entrypoint only. Add hostname to existing private DNS discovery and
inventory; reuse wildcard TLS. Native Kuma authentication stays enabled; no
Funnel route, anonymous status page or new Octelium service.

Add exact `cluster.local/ns/monitoring/sa/uptime-kuma` access only to selected
backend health ports and Prometheus query access, with matching intended network
peers. Incoming Kuma traffic allows Traefik only; bootstrap/reconcile is
loopback. Restrict egress to DNS and catalog targets. Current network enforcement
limits must be described; namespace-wide grants and authentication disablement
are forbidden. Select app endpoints to minimize extra grants.

### Backup, recovery and rollback

Use Python bundled in the same pinned Kuma image (verified 3.11.2/SQLite
3.40.1 with Connection.backup) for SQLite online backup into a local temporary directory, run
`PRAGMA integrity_check`, include `db-config.json` and permitted ancillary
uploads, then checksum and atomically publish archive+manifest to NFS. Reject
symlinks/path traversal, close connections, never copy a live WAL database as a
plain file and never archive secret mounts. Backups contain account hashes and
possibly private monitoring data: logs expose counts/digests only.

Run first backup after successful configuration using a bounded declared Job,
then nightly at 04:20 America/Los_Angeles, retain 14 successful daily copies.
Use `Forbid` and deadlines. Source PVC is read-only for the backup process;
validate live WAL backup in integration before rollout. Keep last valid archive
on failure. NFS backup and local volume have distinct node failure domains but
NAS backups are not off-site disaster recovery. Initial RPO is 24 hours plus
job tolerance; restore is operator-triggered through reviewed GitOps, not HA.

A declared verification Job restores the latest verified archive into emptyDir.
It never mounts the production database or changes production credentials. The
archive and manifest remain read-only and unchanged. Before modifying the clone,
verify the manifest and capture its exact monitor identities, user identity/auth
rows and history summaries/digests privately. Preserve this evidence independently
of the execution-fenced clone; print only sanitized counts and pass/fail.

**Execution fence before native startup:** in one offline transaction, change
only the disposable clone: set every monitor.active=0; set every notification's
active and is_default to 0; delete monitor_notification bindings; set every
maintenance.active=0; and upsert JSON-encoded setting values checkUpdate=false,
nscd=false and cloudflaredTunnelToken="". Retain notification definitions and all
other monitor fields, accounts and historical records. Check the pinned schema,
column types and unique setting keys first; reject unsupported/missing columns,
ambiguous settings or unsafe state. Require exactly one row for each fenced
setting and confirm its decoded value, zero nonzero/null monitor/notification/
maintenance activation flags, zero notification bindings and unchanged user,
monitor identity and history evidence after commit and after reopening the DB.
No native process may start on a failed fence or verification.

Start only the pinned native server, bound to 127.0.0.1, with a minimal explicit
child environment (PATH and necessary temporary/home paths only); do not inherit
NODE_OPTIONS, proxy, cloudflared-token or Kuma configuration overrides. Its argv
contains no tunnel option. The verifier performs needSetup=false, native login
without allowSetup, read-only identity/history checks, then bounded shutdown.
It must never call bootstrap, reconcile, resume, setup, notification-test or
settings-write APIs. Pausing the disposable clone is an explicit verification
exception, not production configuration or a production recovery procedure.

Use a dedicated uptime-kuma-restore service account with no token mount, RBAC,
backend grants or source-PVC mount. Keep deny-all NetworkPolicy as desired
additional defense, but do not describe it as enforced isolation: current
Flannel networking and staged kube-router do not establish enforcement. The
primary guarantee is version-bound application execution fencing, not a general
network sandbox. Pinned startup source also performs version checks and tunnel
auto-start, hence their settings/environment fences are mandatory. Unreviewed
startup behavior or a changed image/schema fails acceptance until re-evaluated.

Require network-enabled positive/negative integration proving probe and
notification sinks are reachable and a positive unfenced fixture emits traffic,
then proving a fenced clone emits none while native login and history checks
succeed; also prove updater/tunnel launch is disabled using pinned-source tests
and observable negative controls. See quickstart and native-api contract.
Rollback preserves PV/PVC and backups; schema rollback uses a matching restored
snapshot with the writer stopped through code. Git revert alone is not recovery.

## Delivery sequence and verification

1. Deliver image-only prerequisite plus fixed mirror scope/tests; protected
   merge, exact-main `harbor-mirror.yml image_scope=uptime-kuma`, successful
   full authenticated pull receipts. New consumers remain absent until proven.
2. Implement workload, catalog, adapters, policy grants, SSM/bootstrap/apply lane,
   tests and docs. Run pinned-image behavior tests, render and static/policy
   checks, then protected PR delivery. Existing AppProject already permits
   monitoring and local storage, so do not broaden project permissions.
3. Extend targeted apply for `uptime-kuma` to validate monitoring destination,
   storage, External Secrets, Prometheus and Traefik prerequisites before writes;
   apply the existing shared SSM/reader policy saved-plan lane, then only this
   Application. Inspect unrelated shared-unit changes; never apply a stale plan.
4. Verify source revision, workload and secret readiness, automatic configuration,
   private UI login, every coverage disposition and three observations. Exercise
   disposable failure/recovery through a repo-owned acceptance command, never
   stop an existing app. Reapply config and perform one declared replacement.
5. Prove first backup and isolated restore, recheck exact deployed revision,
   record target outages separately and complete only after convergence.

Implementation must add runnable validation/acceptance commands described in
[quickstart.md](quickstart.md); names there are planned interfaces until built.
No user-facing approval round is added by this plan.
