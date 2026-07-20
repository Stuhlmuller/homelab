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
Redis, blob storage, and config state; Prometheus, Grafana, Deluge, media-postgres,
n8n-postgres, octelium-storage PostgreSQL/Redis, Octelium Enterprise package
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

`affine-postgres` tolerates 30 minutes of startup or liveness failures and uses
a 120-second termination grace period. Its single-replica container startup
removes a stale `postmaster.pid` from an already-terminated predecessor so an
NFS interruption cannot leave the database in a permission-denied crash loop.
The PVC remains retained and is never recreated as part of this recovery path.

`media-postgres` protects NFS-backed crash recovery with a 30-minute startup
probe and a 120-second termination grace period. Readiness still requires
`pg_isready`, so Prowlarr, Radarr, and Sonarr cannot reach PostgreSQL until
recovery completes. See `clusters/homelab/apps/media-postgres/README.md` for the
failure mode and operator response.

## Source Files

- `docs/storage-nfs.md`
- `clusters/homelab/platform/storage`
- `clusters/homelab/apps/deluge/media-storage.yaml`
- `clusters/homelab/apps/radarr/media-storage.yaml`
- `clusters/homelab/apps/sonarr/media-storage.yaml`
- `IaC/live/argocd-apps/platform-storage`
