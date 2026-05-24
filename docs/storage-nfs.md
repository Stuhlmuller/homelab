# NFS Storage

Stateful apps use a default QNAP-backed NFS StorageClass named `nfs-default`
unless an app-specific exception is documented here.

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

NFS is enabled from QTS at Control Panel > Network & File Services >
Win/Mac/NFS/WebDAV > NFS Service. The current NAS configuration enables
NFSv2/NFSv3, and Kubernetes mounts the export with `nfsvers=3`.

The `homelab` shared folder grants NFS read/write access only to the Talos node
addresses:

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

Expected result:

```text
Exports list on 10.1.0.2:
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
| `nfs.mountOptions` | `nfsvers=3` | Matches the enabled QNAP NFS service |
| StorageClass | `nfs-default` | Stable class name for homelab PVCs |
| `defaultClass` | `true` | Allows ordinary PVCs to bind without per-app overrides |
| `provisionerName` | `k8s-sigs.io/qnap-nfs` | Stable provisioner identity |
| `accessModes` | `ReadWriteMany` | NFS can support multi-node mounts |
| `reclaimPolicy` | `Retain` | Protects workload data from accidental PVC deletion |
| `allowVolumeExpansion` | `true` | Allows planned PVC growth |

The parent `platform-storage` Application auto-syncs by default. Treat it as a
readiness gate anyway: verify the QNAP export is visible and the child
provisioner Application is healthy before relying on stateful workload PVCs.

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

| App | Data classes | StorageClass | Backup expectation | Restore expectation | Rollback data behavior |
|-----|--------------|--------------|--------------------|---------------------|------------------------|
| prometheus | metrics | `nfs-default` | NFS backup or metrics retention acceptance | Restore PVC or accept documented metrics loss | Preserve PVC unless explicitly deleting metrics |
| grafana | dashboards, config | `nfs-default` | NFS backup plus dashboard export when possible | Restore PVC and re-sync dashboards | Preserve PVC |
| deluge | config, downloads | `nfs-default` | NFS backup for config and download paths | Restore config/download PVCs before app sync | Preserve PVCs |
| radarr | config, media refs | `nfs-default` | NFS backup for config and shared media references | Restore config PVC and verify media mount refs | Preserve PVC |
| sonarr | config, media refs | `nfs-default` | NFS backup for config and shared media references | Restore config PVC and verify media mount refs | Preserve PVC |
| litellm | model routing, optional DB/config | `nfs-default` | NFS backup for config store or DB PVC | Restore PVC before exposing gateway | Snapshot first, preserve PVC |
| openclaw | config, runtime state | `nfs-default` | NFS backup for runtime state | Restore PVC and verify LiteLLM connectivity | Preserve PVC |
| tines | automation history, config | `nfs-default` | NFS backup plus app export when available | Restore PVC before worker/web sync | Snapshot first, preserve PVC |

## Validation Notes

- Read-only `showmount -e 10.1.0.2` verified `/homelab` is exported only to
  `10.1.0.199`, `10.1.0.200`, `10.1.0.201`, and `10.1.0.202`.
- Read-only `kubectl get storageclass` reported no resources before this
  storage integration was added.
- Persistent app Terragrunt units were checked on 2026-05-24. Prometheus,
  Grafana, Deluge, Radarr, Sonarr, LiteLLM, OpenClaw, and Tines each explicitly
  depend on `IaC/live/argocd-apps/platform-storage`.
- The live `nfs-subdir-external-provisioner` Application was verified healthy
  on 2026-05-24.
- A temporary PVC smoke test on 2026-05-24 dynamically provisioned storage,
  mounted it into a pod, wrote `smoke.txt`, read it back, and then removed the
  temporary PVC, pod, and smoke-test StorageClass.
