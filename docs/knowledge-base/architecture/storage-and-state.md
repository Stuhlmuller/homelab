# Storage And State

Tags: #architecture #storage #stateful

## Durable Storage

Kubernetes persistent storage is backed by a QNAP NFS export.

| Setting | Value |
| --- | --- |
| NAS address | `10.1.0.2` |
| Export | `/homelab` |
| StorageClass | `nfs-default` |
| Provisioner | `k8s-sigs.io/qnap-nfs` |
| Reclaim policy | `Retain` |
| Mount option | `nfsvers=3` |

`platform-storage` owns the parent Argo CD Application, and the child
`nfs-subdir-external-provisioner` Application owns the StorageClass.

`media-postgres` is an explicit exception. Its active 20 Gi volume is a
retained static `hostPath` PV at `/var/lib/media-postgres`, pinned to `acer`;
the former NFS data claim remains retained for verified nightly logical backups
at 03:00 `America/Los_Angeles` with 14-day retention. The local volume removes
QNAP latency from the live database but couples recovery to the single
control-plane node and its system disk.

Media-library paths are intentionally separate from app state. Deluge, Radarr,
and Sonarr use static PV/PVC pairs against the QNAP `/media` export for
downloads, movies, and TV library data. Read-only `showmount -e 10.1.0.2`
verified `/media` and `/homelab` on 2026-05-26.

## Stateful Workload Gate

Stateful workloads can be registered before they are considered operationally
ready, but they must not be treated as production-ready until:

1. `platform-storage` is synced and healthy.
2. `nfs-default` exists and provisions PVCs correctly.
3. A PVC write, delete, and recreate smoke test has passed or an exception is
   recorded.
4. Backup and restore expectations are documented in `docs/storage-nfs.md`.

## Stateful Apps

The current stateful set includes AFFiNE with PostgreSQL/pgvector, ephemeral
Redis, blob storage, and config state; Prometheus, Grafana, Deluge, Dispatcharr
with dedicated PostgreSQL, media-postgres, n8n-postgres, octelium-storage
PostgreSQL/Redis, Octelium Enterprise package
stores (`octelium-rscstore`, `octelium-logstore`, `octelium-metricstore`),
Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, n8n, and OctoBot. See
[[workloads/inventory]] for ownership and dependency notes.
The Octelium Enterprise package stores are DuckDB-backed single-writer stores,
so their Deployments must use `Recreate` rather than rolling updates.

AFFiNE Redis deliberately disables AOF and RDB persistence and uses node-local
`emptyDir` storage, matching the upstream deployment's ephemeral Redis model.
This prevents per-second AOF `fsync` calls and snapshot/AOF rewrite bursts from
reaching the QNAP. PostgreSQL remains durable on NFS with WAL compression and
checkpoint pacing; synchronous commit remains enabled.

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

`media-postgres` uses 30-minute startup and runtime liveness windows plus a
120-second termination grace period. Its readiness probe executes `SELECT 1`
instead of treating socket acceptance as usable database service. The writable
`media-postgres-local` StatefulSet mounts only local storage; a one-time
PID/socket fence prevents it from overlapping the staged writer. The legacy
NFS-backed StatefulSet stays declared at zero replicas, and the sibling
`media-postgres-recovery` overlay fences the writer and backup schedule before
a logical restore. See `clusters/homelab/apps/media-postgres/README.md` for the
failure mode and operator response.

`octelium-postgres` keeps the 30-minute startup window but uses a 90-second
runtime liveness window. Its readiness and liveness checks execute `SELECT 1`,
preventing a server that accepts connections but cannot execute queries from
remaining falsely healthy. It is pinned to `zimaboard-1` to avoid the worst
observed NFS client path, but QNAP NFS remains a database availability risk.
Its availability is required for Octelium service publication, including the
CI Kubernetes API tunnel.

Deluge also uses 30-minute startup and runtime liveness windows so transient NFS
stalls do not force repeated libtorrent state reloads. Its pod runs on
`zimaboard-0` with resource requests, keeping it off the control-plane node
and away from the media PostgreSQL workload on `zimaboard-1`. The Deluge liveness RPC
checks use a 25-second command timeout after read-only inspection on 2026-07-26
found the VPN healthy and Sonarr-to-Deluge HTTP fast while intermittent
`deluge-console status` calls exceeded the old 10-second budget and triggered
probe flaps. The metrics sidecar computes fresh health every 45 seconds with a
20-second RPC cap and a 30-second Prometheus scrape deadline because the old
cached writer wedged for more than a day inside
`timeout 10s deluge-console` and kept serving stale
`deluge_daemon_rpc_healthy 0`. Its startup wrapper skips the pinned LinuxServer
image's recursive `/config` ownership pass because QNAP root squash rejects the
operation and the retained PVC permissions already provide Deluge's write
access. When stale resume data points complete downloads at the incomplete root,
the documented operator script selects only exact-size target files, adopts them
with libtorrent's `dont_replace` move, and requires a full piece-hash recheck
before completion is trusted. The command resumes hash-valid entries for seeding
and pauses hash failures so stale catalog state cannot trigger a silent
redownload.

## Source Files

- `docs/storage-nfs.md`
- `clusters/homelab/platform/storage`
- `clusters/homelab/apps/deluge/media-storage.yaml`
- `clusters/homelab/apps/media-postgres`
- `clusters/homelab/apps/media-postgres-recovery`
- `clusters/homelab/apps/radarr/media-storage.yaml`
- `clusters/homelab/apps/sonarr/media-storage.yaml`
- `IaC/live/argocd-apps/platform-storage`
