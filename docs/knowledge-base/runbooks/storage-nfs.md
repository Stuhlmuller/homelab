# NFS Storage

Tags: #runbooks #storage #nfs #qnap

Source: `docs/storage-nfs.md`

## NAS Configuration

| Setting | Value |
| --- | --- |
| NAS | QNAP TS-451+ |
| Address | `10.1.0.2` |
| Export | `/homelab` |
| StorageClass | `nfs-default` |
| NFS version | `nfsvers=3` |
| Provisioner | `k8s-sigs.io/qnap-nfs` |
| Reclaim policy | `Retain` |

The export allows read/write access only from the Talos node addresses
`10.1.0.199` through `10.1.0.202`. QNAP NFS rules use `sys` security and squash
all users to the NAS `guest` identity.

## GitOps Desired State

`IaC/live/argocd-apps/platform-storage/terragrunt.hcl` registers the parent
`platform-storage` Application. The parent points at
`clusters/homelab/platform/storage`, which creates the child
`nfs-subdir-external-provisioner` Application.

## Validation

Workstation export check:

```sh
showmount -e 10.1.0.2
```

Expected export:

```text
/homelab 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199
```

Render and cluster checks:

```sh
kubectl kustomize clusters/homelab/argocd/self-management
kubectl kustomize clusters/homelab/platform/storage
kubectl -n argocd get application platform-storage nfs-subdir-external-provisioner
kubectl -n storage get deploy,pod
kubectl get storageclass nfs-default
```

Before relying on stateful workloads, create a temporary PVC and pod, write a
file, delete/recreate, and confirm the file survives.

## Backup Gate

NFS backup coverage is a hard readiness gate. Persistent apps are registered
with automated sync, but they are not production-ready until backup and restore
coverage is acceptable.

Current stateful apps include Prometheus, Grafana, Deluge, media-postgres,
Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, n8n, and OctoBot.

## Related Notes

- [[../architecture/storage-and-state]]
- [[../workloads/inventory]]
- [[../workloads/application-notes]]
