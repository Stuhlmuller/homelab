# Platform Storage

This path owns the dynamic provisioners for the homelab cluster.
The parent `platform-storage` Application is registered by the Terragrunt unit
at `IaC/live/argocd-apps/platform-storage` and is automated by default. Its
child Applications install upstream Helm charts into the `storage` namespace:

- `nfs-subdir-external-provisioner` creates the default `nfs-default`
  StorageClass for durable shared storage.
- `cordium-local-path-provisioner` creates the non-default `cordium-local`
  StorageClass. It provisions only on `zimaboard-1` under
  `/var/lib/cordium-workspaces`, where Cordium's rootless Podman runtime can
  enforce private ownership and mode bits that the QNAP NFS export cannot.

`cordium-local` is node-local scratch storage with a `Delete` reclaim policy.
It is not replicated or backed up and must not be used for durable app data.

The NAS-side setup is documented in `docs/storage-nfs.md`. Do not depend on
stateful workloads until the provisioner is healthy and the PVC write, delete,
and recreate validation in that runbook has passed.
