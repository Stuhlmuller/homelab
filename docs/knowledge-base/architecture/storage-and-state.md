# Storage And State

Tags: #architecture #storage #stateful

## Durable Storage

Kubernetes persistent storage is backed by a QNAP NFS export.

| Setting        | Value                  |
| -------------- | ---------------------- |
| NAS address    | `10.1.0.2`             |
| Export         | `/homelab`             |
| StorageClass   | `nfs-default`          |
| Provisioner    | `k8s-sigs.io/qnap-nfs` |
| Reclaim policy | `Retain`               |
| Mount option   | `nfsvers=3`            |

`platform-storage` owns the parent Argo CD Application, and the child
`nfs-subdir-external-provisioner` Application owns the StorageClass.

Cordium Workspaces are the deliberate exception to the NFS default. The
`cordium-local` StorageClass dynamically provisions disposable `hostPath`
volumes under `/var/lib/cordium-workspaces` on `zimaboard-1`. Rootless Podman
requires private ownership and mode bits for its runtime directory, which the
QNAP NFSv3 export does not preserve. These volumes use a `Delete` reclaim
policy and have no replication or backup; they are development scratch space,
not durable workload storage. The provisioner and its `hostPath` helper Pods
run in the dedicated privileged `cordium-storage` namespace so the broader
`storage` namespace can keep baseline Pod Security enforcement.
The Cordium worker patch also sets `user.max_user_namespaces=28633` only on
`zimaboard-1`, because each Workspace starts a rootless Podman container and
Talos otherwise disables the required user namespaces. The Cordium Application
also owns a node-pinned DaemonSet whose root init container can write only that
host sysctl file whenever GitOps or a node reboot recreates the Pod. The init
container is privileged because Talos protects host sysctls even from UID 0;
the steady-state container is unprivileged and exposes readiness from the live
value.

`media-postgres` is an explicit exception. Its active 20 Gi volume is a
retained static `hostPath` PV at `/var/lib/media-postgres`, pinned to `acer`;
the former NFS data claim remains retained for verified nightly logical backups
at 03:00 `America/Los_Angeles` with 14-day retention. The local volume removes
QNAP latency from the live database but couples recovery to the single
control-plane node and its system disk. GitOps explicitly declares the retained
`data-media-postgres-0` claim with `Prune=false,Delete=false`; the inactive
legacy StatefulSet keeps its compatible claim template for rollback. A clean
bootstrap therefore creates the backup target even while that StatefulSet stays
at zero replicas.

Media-library paths are intentionally separate from app state. Deluge, Radarr,
and Sonarr keep active app config on retained local volumes pinned to
`zimaboard-0`, while using retained NFS claims as migration sources and nightly
archive targets. Their media paths still use static PV/PVC pairs against the
QNAP `/media` export for downloads, movies, and TV library data. Read-only
`showmount -e 10.1.0.2` verified `/media` and `/homelab` on 2026-05-26.

## Stateful Workload Gate

Stateful workloads can be registered before they are considered operationally
ready, but they must not be treated as production-ready until:

1. `platform-storage` is synced and healthy.
2. `nfs-default` exists and provisions PVCs correctly.
3. A PVC write, delete, and recreate smoke test has passed or an exception is
   recorded.
4. Backup and restore expectations are documented in `docs/storage-nfs.md`.

## Open Audit Findings

- **Status:** config recovery verified; session-warning fix staged
- **Area:** OpenClaw upgrade / config and session migration
- **Evidence:** On 2026-09-04, OpenClaw 2026.8.2 bootstrap repeatedly rejected
  four retired config keys before Discord installation and session migration.
  `clusters/homelab/apps/openclaw/values.yaml` now migrates those keys after
  the verified offline backup and preserves legacy model restrictions explicitly.
  It also stops writing retired `hooks.maxBodyBytes`. PR #953 rolled out on
  September 5: both archive verification passes succeeded, retired keys were
  absent, the model policy was present, and Discord 2026.8.2 installed.
  Session dry-run then stopped on one missing healthcheck transcript: 19 of 20
  entries validated, with 1,089 events. Upstream treats `transcript_missing` as
  an import warning and preserves metadata, but its CLI returns exit 1 for all
  issues. Bootstrap now accepts only that exact known agent/session warning,
  retains private JSON reports, and rejects all other issues. No live index
  entries or transcripts were manually altered.
- **Validation:** A synthetic legacy config failed under the exact 2026.8.2
  CLI before migration and passed afterward. The actual bootstrap migration
  has preservation, idempotence, and invalid-input checks in
  `scripts/ci/openclaw-config-check.py`. The same check exercises the session
  report gate against unexpected warnings, failure exits, mismatched reports,
  and malformed JSON. An exact 2026.8.2 CLI fixture returned exit 1 for
  dry-run and import with a missing transcript, preserved both session metadata
  entries, and passed post-import inspection. Full static validation, 280
  rendered policy checks, shell syntax, and server-side diff passed.
- **Next step:** Roll out through GitOps, require successful bootstrap and
  session migration, then verify gateway and Discord readiness. Preserve the
  pre-upgrade archive and migration originals until the 24-hour soak passes.

- **Status:** open
- **Area:** storage / backup and retained data
- **Evidence:** Read-only inspection on 2026-08-27 found Prometheus and
  Alertmanager on `nfs-default`; Prometheus warns that `NFS_SUPER_MAGIC` is
  unsupported and can cause data corruption or loss. All 37 `nfs-default`
  PVCs, three `media-qnap-static` claims, and the provisioner's NFS claim are
  bound, but the repository proves neither an independent off-NAS backup nor a
  tested restore. Eight `Released` PVs retain old data, and the QNAP still
  advertises NFSv2 even though Kubernetes mounts NFSv3.
- **Risk:** Monitoring data can corrupt, a NAS failure can remove every copy,
  and blind retained-volume cleanup can destroy unrecovered data.
- **Next step:** Choose an independent backup target and prove restores. Move
  Prometheus and Alertmanager through a backed-up, fenced migration to
  supported repo-owned block or local storage. Map each retained PV before
  owner-approved cleanup. Add a declared QNAP management path before disabling
  NFSv2, and first confirm no other client needs it.

## Stateful Apps

The current stateful set includes AFFiNE with PostgreSQL/pgvector, ephemeral
Redis, blob storage, and config state; Prometheus, Grafana, Deluge, Dispatcharr
with dedicated PostgreSQL, media-postgres, Multica with pgvector PostgreSQL and
backend upload PVCs, n8n-postgres, octelium-storage PostgreSQL/Redis, Octelium
Enterprise package stores (`octelium-rscstore`, `octelium-logstore`,
`octelium-metricstore`), Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, n8n,
NOFX SQLite state, and OctoBot. OpenClaw keeps auth, sessions, workspace, and
application state on its PVC, but mounts its rebuildable per-agent Codex
app-server home from a
pod-local `emptyDir` so native thread backfills and diagnostics cannot stall
turns over NFS. The volume is capped at `2Gi` to protect node storage. See
[[workloads/inventory]] for ownership and dependency notes.
The Octelium Enterprise package stores are DuckDB-backed single-writer stores,
so their Deployments must use `Recreate` rather than rolling updates.
Multica PostgreSQL now follows the recovered NFS database probe pattern:
30-minute startup and liveness windows, SQL-query readiness, and 120-second
shutdown grace. Its image, credentials, scheduling, and PVC are unchanged.
This prevents short liveness windows from interrupting recovery; it does not
resolve the underlying NFS reliability or backup risks.
The latest rscstore recovery preserves the unreplayable 2026-08-26 DuckDB WAL
by renaming it on the retained PVC before starting from the last valid
checkpoint. A new completion marker leaves the earlier 2026-08-21 recovery
artifacts untouched and makes retries read-only; quarantined WALs are not
deleted automatically. Recovery fails closed rather than overwrite a dated
quarantine if its completion marker is missing.

AFFiNE Redis deliberately disables AOF and RDB persistence and uses node-local
`emptyDir` storage, matching the upstream deployment's ephemeral Redis model.
This prevents per-second AOF `fsync` calls and snapshot/AOF rewrite bursts from
reaching the QNAP. PostgreSQL remains durable on NFS with WAL compression and
checkpoint pacing; synchronous commit remains enabled. The former Redis AOF
claim remains retained for rollback but is no longer mounted by Redis.

`affine-postgres` was fenced at zero replicas during the first phase of the
2026-07-20 stale-lock recovery; live validation confirmed the pod was absent
and its retained PVC stayed bound. The second phase declares that claim as an
early Argo CD resource and used the idempotent
`affine-postgres-stale-lock-recovery-20260720` Sync hook to remove only
`postmaster.pid` before Argo CD restored one replica. The hook wrote a durable
completion marker on the PVC, PostgreSQL completed crash recovery, and live
validation passed with zero pod restarts. The incident-only hook is now removed
from desired state, while the explicit retained claim, 30-minute startup and
liveness windows, and 120-second termination grace remain.

`n8n-postgres` completed its fenced 2026-08-03 stale-lock recovery. The
incident hook removed only `postmaster.pid`, wrote a durable marker, and
restored one replica with zero PostgreSQL restarts. Live checks passed for SQL,
n8n readiness, and the public callback. The hook is now removed; the explicit
retained claim, 30-minute startup and liveness windows, and 120-second
termination grace remain.

`media-postgres` uses 30-minute startup and runtime liveness windows plus a
120-second termination grace period. Its readiness and liveness probes execute
`SELECT 1` instead of treating socket acceptance as usable database service.
The writable `media-postgres-local` StatefulSet mounts only local storage; a
one-time PID/socket fence prevents it from overlapping the staged writer. The
legacy NFS-backed StatefulSet stays declared at zero replicas, and the sibling
`media-postgres-recovery` overlay fences the writer and backup schedule before
a logical restore. See `clusters/homelab/apps/media-postgres/README.md` for the
failure mode and operator response.

`octelium-postgres` keeps the 30-minute startup window but uses a 90-second
runtime liveness window. Its readiness and liveness checks execute `SELECT 1`,
preventing a server that accepts connections but cannot execute queries from
remaining falsely healthy. It is pinned to `zimaboard-1` to avoid the worst
observed NFS client path, but QNAP NFS remains a database availability risk.
Its availability is required for Octelium service publication, including the
CI Kubernetes API tunnel. A daily CronJob writes PostgreSQL globals without
password hashes, a custom-format database dump, and checksums to the separate
retained `octelium-postgres-backup` NFS claim. It verifies the dump before
atomic publication and retains 14 days. This is a logical recovery and
migration checkpoint, not an off-NAS backup; restore validation remains open.
Grafana's shared backup-staleness rule includes this CronJob alongside the four
media backup jobs: warn after 30 hours without success, including an established
job that has never succeeded. The legacy rule UID is preserved during expansion.

Multica uses the standard `nfs-default` class for its dedicated pgvector
PostgreSQL data and backend uploads. Treat those claims as a matched recovery
set: restore the database and upload PVCs from the same backup point before
resuming app sync, and preserve both PVCs during rollback unless intentionally
rebuilding the Multica instance. The first rollout is registered as stateful but
should stay in the stateful workload gate until backup and restore validation is
completed in `docs/storage-nfs.md`.

NOFX uses a single retained `nfs-default` claim for backend SQLite data and log
state at `/app/data`. The first rollout is registered as stateful but should
stay in the stateful workload gate until PVC smoke testing and backup/restore
expectations are recorded in `docs/storage-nfs.md`.

Deluge's active 5 Gi config volume is a retained static `hostPath` PV at
`/var/lib/deluge`, pinned to `zimaboard-0`. The initial guarded cold copy took
4 minutes 6 seconds for roughly 5.2 MB, demonstrating the QNAP stall on the old
startup path. The steady-state pod mounts only local config and shared
downloads; the old `deluge-config` claim receives verified nightly archives
with 14-day retention. This removes catalog, fast-resume, authentication, and
health-command reads from the QNAP path after read-only inspection on
2026-07-30 found the VPN healthy while the previous pod reported failed daemon
RPC health for roughly 17 hours. Its clean replacement loaded all 17 torrents
with no error-state entries and zero container restarts. An ordinary
`deluge-console status` still took 13 seconds on local config, so the existing
bounded health timeout remains necessary even though NFS is no longer in that
path.
The first scheduled NFS archive, `20260731T103003Z.tar.gz`, completed and passed
the CronJob's archive listing validation.

Radarr and Sonarr use retained static 10 Gi `hostPath` config volumes at
`/var/lib/radarr` and `/var/lib/sonarr`, pinned to `zimaboard-0`. Their guarded
`Recreate` cutovers copied the retained NFS config trees and recovered invalid
configuration before PostgreSQL/auth normalization. Migration markers make the
copies idempotent, while the old NFS claims remain archive and rollback targets.
The 04:00 and 04:15 Pacific CronJobs write verified archives with 14-day
retention. Read-only inspection on 2026-08-27 found both Applications `Synced`,
both local claims `Bound`, and successful backup Jobs through 2026-08-25. The
steady app pods no longer mount the legacy NFS claims; only the backup CronJobs
mount them as archive and rollback targets.

Deluge keeps 30-minute startup and runtime liveness windows so guarded
libtorrent recovery is not interrupted. The metrics sidecar refreshes cached
health every 60 seconds with a 20-second RPC cap; Prometheus scrapes that cache
every 45 seconds with a 30-second deadline. When stale resume data points
complete downloads at the incomplete root, the documented operator script
selects only exact-size target files, adopts them with libtorrent's
`dont_replace` move, and requires a full piece-hash recheck before completion is
trusted. The command resumes hash-valid entries for seeding and pauses hash
failures so stale catalog state cannot trigger a silent redownload.

## Source Files

- `docs/storage-nfs.md`
- `clusters/homelab/platform/storage`
- `clusters/homelab/apps/cordium-bootstrap/cluster-config.yaml`
- `clusters/homelab/apps/multica`
- `.talos/patches/worker-zimaboard-1.yaml`
- `.talos/patches/worker-cordium-user-namespaces.yaml`
- `.talos/patches/worker-cordium-user-namespaces-rollback.yaml`
- `clusters/homelab/apps/deluge/media-storage.yaml`
- `clusters/homelab/apps/deluge/local-storage.yaml`
- `clusters/homelab/apps/radarr/local-storage.yaml`
- `clusters/homelab/apps/sonarr/local-storage.yaml`
- `clusters/homelab/apps/media-postgres`
- `clusters/homelab/apps/media-postgres-recovery`
- `clusters/homelab/apps/octelium-storage`
- `clusters/homelab/apps/radarr/media-storage.yaml`
- `clusters/homelab/apps/sonarr/media-storage.yaml`
- `IaC/live/argocd-apps/platform-storage`

## OpenClaw identity coordinator ownership

September 5 read-only inspection found QNAP-backed OpenClaw paths reported as
UID/GID `65534`; the 2026.8.2 runtime uses UID `1000`. Its new private
coordinator ownership check blocked gateway startup after session migration
completed successfully. The repository mounts a shared local `emptyDir` at
`/data/openclaw/tmp/openclaw-1000`, initialized to `1000:1000`, mode `0700`.
Only coordinator locks move off NFS; identity/configuration/session databases
and the verified pre-upgrade backup remain on the PVC. This requires one
`Recreate` Pod and all writers using its shared mount. Never start an external
writer against that PVC with a separate coordinator. See the OpenClaw README
for verification and rollback limits; live recovery remains pending rollout.
