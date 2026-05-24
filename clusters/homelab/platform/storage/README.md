# Platform Storage

This path owns the QNAP-backed NFS dynamic provisioner for the homelab cluster.
The parent `platform-storage` Application is registered from Argo CD
self-management as a manual rollout gate. When `platform-storage` is synced, it
creates the child `nfs-subdir-external-provisioner` Application in the `argocd`
namespace. The child Application installs the upstream Helm chart into the
`storage` namespace and creates the default `nfs-default` StorageClass.

The NAS-side setup is documented in `docs/storage-nfs.md`. Do not sync stateful
workload Applications until the provisioner is healthy and the PVC write,
delete, and recreate validation in that runbook has passed.
