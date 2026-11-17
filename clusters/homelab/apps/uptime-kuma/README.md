# Uptime Kuma

Uptime Kuma 2.5.11 runs in `monitoring` behind private Traefik at
`https://uptime-kuma.stinkyboi.com`. Native authentication remains enabled.
The owner is `admin`; its generated password comes from the exact SSM key
`/homelab/uptime-kuma/admin-password` through External Secrets. Retrieve it
through the existing authorized secret-management path; never put it in commands,
logs, tickets or source. Only bootstrap, reconciler and the isolated restore verifier mount this credential.

The repository catalog classifies every registered/live app and maps active apps
to health endpoints or explicit fresh workload signals. Workload readiness is
not proof of an app's full user workflow. A healthy HTTP query is not enough:
Prometheus monitors require positive desired replicas, available/ready state,
observed generation and source timestamps within two actual scrape periods.
Private ingress is checked separately. Existing failed targets stay down.

The pinned image must first be published through the protected fixed
`uptime-kuma` Harbor scope. Registration and SSM prerequisites use the declared
targeted Terragrunt pipeline. Do not substitute direct apply/patch commands.

## Reconciliation and retained state

The main process runs as UID/GID 10001 with a retained 5Gi local PVC
`uptime-kuma-local` on `acer` (`/var/lib/uptime-kuma`). Recreate prevents two
SQLite writers. A bounded ownership init sets only the mount-root ownership;
bootstrap starts a loopback server, creates an owner only when none exists,
checks native login/retention and stops before main starts. Invalid credentials
fail closed and never reset the database or owner.

The sidecar reconciles every 300 seconds. Stable description keys preserve IDs
and history; only owned fields change. Explicit retired entries pause; unowned
monitors and unrelated settings remain intact. Duplicate ownership fails before
writes. The per-cycle lease serializes manual and periodic reconciliations.
To retire a service, keep its app entry, monitor keys and reciprocal
`monitorIds`/`ownerAppIds` links in `monitors.json`. Set the app lifecycle to
`retired`, explain the retirement in `reason`, and point `source` to retained
owning documentation containing an identity-bound declaration:

```html
<!-- uptime-kuma-retired: former-service -->
```

Replace `former-service` with the app ID. Keep this evidence after removing the
old stack, so historical app IDs remain verifiable. Set exclusively retired
monitors to `enabled: false`; reconciliation pauses them in place, preserving
IDs and history. Do not remove their records. A monitor shared with an active
owner must stay enabled; retirement of one owner must not stop another owner's
coverage. Every active or configuration-only app still needs enabled meaningful
coverage. A disabled old monitor can remain alongside its active replacement.
Suspended/staged apps may likewise retain disabled records, but their owning
source must still prove zero replicas or disabled activation.

Validate the transition before normal PR/GitOps delivery:

```sh
python3 scripts/ci/uptime-kuma-check.py
```

Run the repository-owned adapter to verify repeatability:

```sh
kubectl -n monitoring exec deploy/uptime-kuma -c reconciler -- node /config/reconcile.js once
kubectl -n monitoring exec deploy/uptime-kuma -c reconciler -- node /config/reconcile.js once
kubectl -n monitoring exec deploy/uptime-kuma -c reconciler -- node /config/reconcile.js health
```

A zero-change second run must retain IDs and prior heartbeat observations.
`/status/reconcile.json` contains only catalog hash, time, counts and sanitized
error category. Readiness fails after an unsuccessful reconciliation. To test
replacement, commit a new `controllers.uptime-kuma.pod.annotations` rollout
revision in `values.yaml`, deliver it through the normal protected PR/GitOps
path, and compare monitor IDs/history afterward. Do not delete a live Pod or PVC
to manufacture this test. Config updates retain a stable ConfigMap name so the
sidecar reads the next projected catalog without resetting state.

## Backup and isolated restore

The first declared backup Job waits up to 600 seconds for catalog coverage and
nonempty heartbeat history. The CronJob runs at 04:20 `America/Los_Angeles`,
forbids overlapping scheduled runs, and keeps 14 successful bundles under
`/backups/snapshots` on the 5Gi `uptime-kuma-backups` NFS PVC. Jobs have 900-second
deadlines. The source PVC mounts read-only. Python's online SQLite backup reads
the live WAL transactionally into a bounded 5Gi local scratch volume, validates
integrity, and writes only a complete standalone snapshot.

Each private bundle contains `data.tar.gz` plus `manifest.json`: checksum,
capture time, source image digest, catalog hash, integrity and monitor/history
counts. Only the database, SQLite config and regular files under `upload/` are
included. Mounted credentials, WAL/SHM files and arbitrary data-directory files
are excluded. Symlinks and traversal are rejected. Archive and manifest become
visible together via directory rename; failure preserves previous valid bundles.
The backup contains account hashes and private monitor data and must remain
private. A full backup volume fails safely; monitor job failures and capacity.

`uptime-kuma-restore-verification-v1` runs after initial backup. It mounts backup
storage read-only and restores into an empty ephemeral volume; it has no
production data mount. A dedicated service account has no production grants or API token. The declared
deny-all policy is defense in depth: the current Flannel cluster does not
enforce it generally, so it is not evidence of network isolation. Before any
native process starts, the verifier validates the pinned SQLite schema, records
private identity/history evidence, then transactionally fences only its emptyDir
clone: pause monitors, deactivate notifications/defaults and maintenance, remove
notification bindings, disable updates/NSCD and empty the tunnel token. It
reopens SQLite and verifies every fence and unchanged permitted evidence. Unknown
schema, duplicate settings, unexpected flags or missing postconditions fail
before startup. The newly restored clone is discarded on success or fence/native
failure; a preexisting destination is rejected and preserved. Original archives
and production data are never changed.

The same pinned server starts on loopback with a fixed child environment that
excludes inherited Node, proxy, Kuma and tunnel overrides. Native needSetup must
be false, owner login must succeed, and read-only list/detail/history must prove
retained identities and observations; no setup, resume, notification test or
reconciliation is allowed in the verifier. Monitor
IDs must match the captured snapshot, and saved heartbeat history must remain.
The mounted owner credential is used only for this isolated login and never
archived. Malformed, incomplete, corrupt or mismatched-version bundles fail.
To repeat the declared first-backup or restore Jobs, change their version suffix
in source and deliver via GitOps; inspect sanitized logs and Job completion.

```sh
kubectl -n monitoring logs job/uptime-kuma-first-backup-v1
kubectl -n monitoring logs job/uptime-kuma-restore-verification-v1
kubectl -n monitoring get cronjob uptime-kuma-backup
```

Local verification uses disposable storage and the exact image:

```sh
python3 scripts/ci/uptime-kuma-backup-test.py
bash scripts/ci/uptime-kuma-backup-integration.sh
```

The local disk and NAS are distinct failure domains, but this is not HA or an
external disaster-recovery copy. A lost `acer` volume needs restoration; a lost
NAS loses archives. Nominal RPO is 24 hours plus scheduler/job delay. HostPath 5Gi
is a scheduling declaration, not an enforced filesystem quota. Retained data
and backup PVCs must not be pruned during rollout or rollback.

For production recovery, first fence the writer through a reviewed replicas 0
change. Preserve a pre-recovery snapshot where possible, verify the chosen
bundle in isolation, and deliver a narrowly scoped recovery Job in source with
the exact matching image/schema. Only that fenced recovery workflow may write
the production volume. Then restore the reviewed replica count and verify
native login, IDs, history and monitor observations. The shipped `verify` mode
is deliberately isolated and is not a production-restore shortcut. A Git revert
cannot undo a database schema migration; use a compatible snapshot and image.

The pinned integration includes a network-enabled positive control that reaches
local probe and webhook sinks, then observes the fenced clone for at least two
configured monitor intervals without either action. Actual pinned update/tunnel
guards run with observable call counters and no public-service requests. This
is a version-bound application execution fence, not a general network sandbox;
image/schema changes require renewed guard and network-enabled acceptance.
