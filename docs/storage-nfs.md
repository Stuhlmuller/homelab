# NFS Storage

Stateful apps use a default NFS-backed StorageClass named `nfs-default` unless
an app-specific exception is documented here.

## Read-Only Inspection

Read-only inspection was attempted on 2026-05-24:

```sh
kubectl get storageclass -o yaml
kubectl get storageclass
kubectl get deployments -A
kubectl get pods -A
kubectl get csidrivers
```

Observed result:

- No StorageClass resources were present.
- No CSI drivers were present.
- No NFS provisioner deployment or pod was present.
- Argo CD and core Kubernetes components were present.

This means the required existing NFS provisioner is not currently available in
the inspected cluster. Stateful rollout is blocked until an NFS provisioner
exists and this document is updated with the public-safe provisioner name and
parameters.

## Default StorageClass Desired State

`clusters/homelab/platform/storage/default-nfs-storageclass.yaml` contains the
intended default StorageClass shape using the common `nfs.csi.k8s.io`
provisioner and public-safe placeholder server/share values. The support
Application `platform-storage` is registered without auto-sync because applying
the StorageClass before the provisioner exists would create a misleading
default.

Before live rollout:

1. Install or identify the existing NFS provisioner outside this feature.
2. Replace placeholder server/share values with public-safe values or safe
   references.
3. Confirm NFS backup coverage for every persistent data class below.
4. Sync `platform-storage`.
5. Sync stateful applications only after PVC provisioning is verified.

## Backup Coverage

NFS backup coverage is a hard rollout gate. Until the provisioner and backup
job are documented, persistent apps are registered but not auto-synced.

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

`kubectl get storageclass` currently reports no resources. This is safe for
repository work but blocks live stateful rollout.

Persistent app Terragrunt units were checked on 2026-05-24. Prometheus,
Grafana, Deluge, Radarr, Sonarr, LiteLLM, OpenClaw, and Tines each explicitly
depend on `IaC/live/argocd-apps/platform-storage`.
