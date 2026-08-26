# NFS Storage

Stateful apps use a default QNAP-backed NFS StorageClass named `nfs-default`
unless an app-specific exception is documented here.

`media-postgres` is the first database exception: its active PostgreSQL data is
on a static node-local volume on `acer`. The retained NFS claim stores verified
nightly logical backups at 03:00 `America/Los_Angeles` with 14-day retention.
The nominal RPO is 24 hours, but the actual RPO is the age of the newest
verified set and can exceed that; backup freshness remains a manual check while
kube-state-metrics alerting is unavailable.

## NAS Configuration

| Setting | Value |
| --- | --- |
| NAS | QNAP TS-451+ |
| NAS address | `10.1.0.2` |
| QTS version at setup | `5.2.9.3451` |
| Storage pool | `Storage Pool 1` |
| Pool layout | RAID 5 across four 2 TB disks |
| Snapshot reserve | 10% |
| Kubernetes volume | `Homelab (System)` |
| Kubernetes shared folder | `homelab` |
| NFS export path | `/homelab` |
| Media shared folder | `Media` |
| Media NFS export path | `/media` |

NFS is enabled from QTS at Control Panel > Network & File Services >
Win/Mac/NFS/WebDAV > NFS Service. Kubernetes mounts the export with
`nfsvers=3`.

Security audit note from 2026-05-25: read-only `rpcinfo -p 10.1.0.2` showed
the NAS advertising both NFSv2 and NFSv3. Kubernetes does not need NFSv2.
Disable NFSv2 in QTS after confirming no non-Kubernetes clients depend on it,
then re-run `rpcinfo -p 10.1.0.2` and confirm only the required NFS version is
advertised.

The `homelab` shared folder grants NFS read/write access only to the Talos node
addresses. The `Media` shared folder must use the same node allow-list before
the media migration is applied:

| Node | Address | Access |
| --- | --- | --- |
| `acer` | `10.1.0.199` | read/write |
| `zimaboard-0` | `10.1.0.200` | read/write |
| `zimaboard-1` | `10.1.0.201` | read/write |
| `zimaboard-2` | `10.1.0.202` | read/write |

The QNAP NFS rules use `sys` security and squash all users to the NAS `guest`
identity. This keeps client-side UIDs from becoming trusted NAS identities and
works with the provisioner-created per-PVC directories. If a workload needs a
specific POSIX owner or mode, document that beside the workload before changing
the NAS export behavior.

Verify the export path and allow-list from an operator workstation:

```sh
showmount -e 10.1.0.2
```

Expected result before media-library cutover:

```text
Exports list on 10.1.0.2:
/homelab 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199
```

Expected result before syncing the Servarr media-storage migration:

```text
Exports list on 10.1.0.2:
/media 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199
/homelab 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199
```

## GitOps Desired State

`IaC/live/argocd-apps/platform-storage/terragrunt.hcl` registers the parent
`platform-storage` Application through the Terragrunt catalog. That parent
points at `clusters/homelab/platform/storage` and auto-syncs by default.

`clusters/homelab/platform/storage/nfs-subdir-external-provisioner-application.yaml`
creates a child Argo CD Application for the upstream
`nfs-subdir-external-provisioner` Helm chart. The child Application creates the
default StorageClass used by stateful workloads.

Important settings:

| Setting | Value | Reason |
| --- | --- | --- |
| Helm chart | `nfs-subdir-external-provisioner` `4.0.18` | Dynamic subdirectory provisioning on the QNAP export |
| Namespace | `storage` | Keeps storage controller resources out of app namespaces |
| `nfs.server` | `10.1.0.2` | QNAP NAS address |
| `nfs.path` | `/homelab` | Export path verified with `showmount` |
| `nfs.mountOptions` | `nfsvers=3` | Matches the Kubernetes-supported NAS NFS mode |
| StorageClass | `nfs-default` | Stable class name for homelab PVCs |
| `defaultClass` | `true` | Allows ordinary PVCs to bind without per-app overrides |
| `provisionerName` | `k8s-sigs.io/qnap-nfs` | Stable provisioner identity |
| `accessModes` | `ReadWriteMany` | NFS can support multi-node mounts |
| `reclaimPolicy` | `Retain` | Protects workload data from accidental PVC deletion |
| `allowVolumeExpansion` | `true` | Allows planned PVC growth |

The parent `platform-storage` Application auto-syncs by default. Treat it as a
readiness gate anyway: verify the QNAP export is visible and the child
provisioner Application is healthy before relying on stateful workload PVCs.

## Static And Local Volume Exceptions

The default `nfs-default` StorageClass remains the path for application config,
most PostgreSQL data, dashboards, metrics, and other app-owned state. The
exceptions are:

- `media-postgres-local`, a retained static `hostPath` PV pinned to `acer` and
  backed by `/var/lib/media-postgres` on the Talos `EPHEMERAL` filesystem.
- `deluge-config-local` and `radarr-config-local`, retained static `hostPath`
  PVs pinned to `zimaboard-0`. Their former NFS config claims remain backup and
  recovery targets rather than active app storage.
- Deluge, Radarr, and Sonarr media-library static PV/PVC pairs that mount the
  QNAP `/media` export directly.

| Claim | Owned by | Mounted in apps | Media subdirectory |
| --- | --- | --- | --- |
| `media-downloads` | `clusters/homelab/apps/deluge/media-storage.yaml` | Deluge, Radarr, Sonarr | `/media/downloads` |
| `media-movies` | `clusters/homelab/apps/radarr/media-storage.yaml` | Radarr | `/media/movies` |
| `media-tv` | `clusters/homelab/apps/sonarr/media-storage.yaml` | Sonarr | `/media/tv` |

Each media app also owns a migration Job that runs as UID/GID `65534`, mounts
the old dynamically provisioned PVC read-only, copies its files into the
corresponding `/media` subdirectory, applies `a+rwX` permissions, and performs a
write test before the app rollout reaches the new volume mounts. The legacy
`deluge-downloads`, `radarr-media`, and `sonarr-media` claims stay in desired
state as migration sources and rollback references until the `/media` copy is
verified. The broad directory mode is intentional for this NAS path because QNAP
NFS squashes Kubernetes client UIDs to the NAS guest identity; the security
boundary is the NAS export allow-list and the cluster namespace, not POSIX
per-user ownership on the export.

## Validation

Before applying the app registrations, render the desired state:

```sh
kubectl kustomize clusters/homelab/argocd/self-management
```

Render the storage desired state:

```sh
kubectl kustomize clusters/homelab/platform/storage
```

After syncing `platform-storage`, verify the child app and StorageClass:

```sh
kubectl -n argocd get application platform-storage nfs-subdir-external-provisioner
kubectl -n storage get deploy,pod
kubectl get storageclass nfs-default
```

Create a temporary PVC and pod that writes a file, delete the pod, recreate it
on another node if possible, and confirm the file is still present before
depending on stateful workloads.

Example PVC:

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: example-nfs-default
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-default
  resources:
    requests:
      storage: 10Gi
```

## Backup Coverage

NFS backup coverage is a hard readiness gate. Persistent apps are registered
with automated sync, but they must not be treated as production-ready until each
app has acceptable backup and restore coverage.

<!-- markdownlint-disable MD013 -->

| App | Data classes | StorageClass | Backup expectation | Restore expectation | Rollback data behavior |
| --- | --- | --- | --- | --- | --- |
| prometheus | metrics | `nfs-default` | NFS backup or metrics retention acceptance | Restore PVC or accept documented metrics loss | Preserve PVC unless explicitly deleting metrics |
| grafana | dashboards, config | `nfs-default` | NFS backup plus repo-owned dashboard and alerting config in `clusters/homelab/apps/grafana` | Restore PVC and re-sync Grafana desired state | Preserve PVC |
| affine | PostgreSQL/pgvector database, uploaded blobs, instance config; ephemeral Redis cache/jobs | `nfs-default` for durable state; node-local `emptyDir` for Redis | Coordinated NFS backup plus `pg_dump` before upgrades; Redis is excluded | Restore PostgreSQL and blob/config claims from one recovery point; Redis rebuilds empty and queued work may be lost | Preserve durable claims and the ECDSA signing key; preserve the inactive, unmounted former Redis AOF claim for manual rollback |
| deluge | active config on `deluge-config-local`, retained NFS config/archive claim, shared downloads on `media-downloads` backed by `/media` | static local config PV plus retained `nfs-default` and static `/media` PV | Nightly verified config archive to NFS with 14-day retention plus `/media/downloads` backup | Stop Deluge, restore one validated config archive into the local claim through a reviewed Job, then verify `/media/downloads` before app sync | Preserve the local PV, retained NFS claim, and `/media/downloads` |
| dispatcharr | file-backed runtime data plus dedicated `dispatcharr-postgres` database | `nfs-default` | NFS backup for data PVC and `dispatcharr-postgres` PVC plus PostgreSQL logical dump | Restore data PVC and `dispatcharr-postgres` PVC or logical dump before app sync | Preserve PVCs and database unless intentionally resetting IPTV state |
| media-postgres | Sonarr, Radarr, and Prowlarr PostgreSQL databases | static `media-postgres-local` on `acer`; retained `nfs-default` backup claim | Nightly role globals without password hashes, six custom-format dumps, and checksums on retained NFS; 14-day retention; nominal 24-hour RPO, but actual RPO is the newest verified set; freshness checked manually until alert telemetry is restored | Fence the writer with the repository recovery overlay, restore globals plus all six matching dumps, then restart the media apps | Preserve both claims; the NFS physical copy is stale after local writes begin |
| multica | pgvector PostgreSQL database and backend uploads | `nfs-default` | NFS backup plus PostgreSQL logical dump before upgrades | Restore database and uploads PVCs from the same recovery point before app sync | Preserve PVCs unless intentionally rebuilding the Multica instance |
| prowlarr | config, indexer refs, PostgreSQL app/log databases | `nfs-default` | NFS backup for config plus PostgreSQL logical dump | Restore config PVC and PostgreSQL databases before app sync and re-test app integrations | Preserve PVCs |
| radarr | active config on `radarr-config-local`, PostgreSQL app/log databases, movies on `media-movies`, shared downloads on `media-downloads` | static local config PV, retained `nfs-default` config/archive claim, local `media-postgres`, and static `/media` PVs | Nightly verified config archive to NFS with 14-day retention, PostgreSQL logical dump, `/media/movies`, and `/media/downloads` | Stop Radarr, restore one validated config archive into the local claim, restore matching PostgreSQL databases if needed, then verify integrations and `/media` paths | Preserve the local PV, retained NFS claim, PostgreSQL backups, and `/media` subdirectories; never reactivate stale NFS config after local writes |
| sonarr | active config on `sonarr-config-local`, PostgreSQL app/log databases, TV on `media-tv`, shared downloads on `media-downloads` | static local config PV, retained `nfs-default` config/archive claim, local `media-postgres`, and static `/media` PVs | Nightly verified config archive to NFS with 14-day retention, PostgreSQL logical dump, `/media/tv`, and `/media/downloads` | Stop Sonarr, restore one validated config archive into the local claim, restore matching PostgreSQL databases if needed, then verify integrations and `/media` paths | Preserve the local PV, retained NFS claim, PostgreSQL backups, and `/media` subdirectories; never reactivate stale NFS config after local writes |
| litellm | model routing, optional DB/config | `nfs-default` | NFS backup for config store or DB PVC | Restore PVC before exposing gateway | Snapshot first, preserve PVC |
| openclaw | config, runtime state | `nfs-default` | NFS backup for runtime state | Restore PVC and verify LiteLLM connectivity | Preserve PVC |
| n8n-postgres | n8n workflows, users, credentials metadata, and execution history | `nfs-default` | NFS backup plus PostgreSQL logical dump before upgrades | Restore PostgreSQL PVC or logical dump before n8n app sync | Preserve PVC unless intentionally rebuilding from exports |
| n8n | instance config, encryption-key settings, and file-backed runtime data | `nfs-default` | NFS backup plus workflow export when available | Restore n8n PVC and n8n-postgres before app sync | Snapshot first, preserve PVC |
| octobot | UI-configured bot state, tentacles, exchange credentials after operator setup, logs, strategy config | `nfs-default` | NFS backup before strategy, tentacle, or exchange-account changes | Restore PVCs before comparing long-running paper/live strategy results or reusing exchange credentials | Preserve PVCs unless intentionally resetting bot credentials |

<!-- markdownlint-enable MD013 -->

## Validation Notes

- Read-only `showmount -e 10.1.0.2` verified `/homelab` is exported only to
  `10.1.0.199`, `10.1.0.200`, `10.1.0.201`, and `10.1.0.202`.
- Read-only `showmount -e 10.1.0.2` on 2026-05-26 verified `/media` and
  `/homelab` are exported to `10.1.0.199`, `10.1.0.200`, `10.1.0.201`, and
  `10.1.0.202`.
- Read-only `kubectl get storageclass` reported no resources before this
  storage integration was added.
- Persistent app Terragrunt units were checked on 2026-05-24 and refreshed for
  OctoBot on 2026-05-26. Prometheus, Grafana, Deluge, Dispatcharr, Prowlarr,
  Radarr, Sonarr, LiteLLM, OpenClaw, n8n, and OctoBot each explicitly depend on
  `IaC/live/argocd-apps/platform-storage`.
- The live `nfs-subdir-external-provisioner` Application was verified healthy
  on 2026-05-24.
- A temporary PVC smoke test on 2026-05-24 dynamically provisioned storage,
  mounted it into a pod, wrote `smoke.txt`, read it back, and then removed the
  temporary PVC, pod, and smoke-test StorageClass.
- Read-only QNAP checks on 2026-05-25 confirmed `/homelab` remains exported
  only to `10.1.0.199`, `10.1.0.200`, `10.1.0.201`, and `10.1.0.202`. The same
  audit found NFSv2 still advertised through RPC; disable it in QTS because the
  Kubernetes StorageClass mounts with NFSv3.
- Read-only inspection on 2026-07-29 measured 311 `media-postgres` NFS writes
  over 20 seconds with roughly 26.9 seconds queued, 8.1 seconds RPC round-trip,
  and 35.0 seconds total execution per write. Concurrent failures affected
  NFS-backed workloads on every active node while all nodes remained Ready and
  physical NIC errors stayed at zero. This evidence drove the local
  `media-postgres` cutover; QNAP remains the backup rather than active database
  path.
