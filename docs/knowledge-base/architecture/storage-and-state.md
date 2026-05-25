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

## Stateful Workload Gate

Stateful workloads can be registered before they are considered operationally
ready, but they must not be treated as production-ready until:

1. `platform-storage` is synced and healthy.
2. `nfs-default` exists and provisions PVCs correctly.
3. A PVC write, delete, and recreate smoke test has passed or an exception is
   recorded.
4. Backup and restore expectations are documented in `docs/storage-nfs.md`.

## Stateful Apps

The current stateful set includes Prometheus, Grafana, Deluge, media-postgres,
Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, n8n, and Hummingbot in the current
working tree. Freqtrade appears only in older or in-flight docs. See
[[workloads/inventory]] for ownership and dependency notes.

## Source Files

- `docs/storage-nfs.md`
- `clusters/homelab/platform/storage`
- `IaC/live/argocd-apps/platform-storage`
