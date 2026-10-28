# Platform Storage

This path owns the dynamic provisioners for the homelab cluster.
The parent `platform-storage` Application is registered by the Terragrunt unit
at `IaC/homelab/us-west-2/apps/platform-storage/stack.hcl` and is automated by
default. Its child Applications install upstream Helm charts into dedicated
namespaces:

- `nfs-subdir-external-provisioner` creates the default `nfs-default`
  StorageClass for durable shared storage.
- `cordium-local-path-provisioner` creates the non-default `cordium-local`
  StorageClass in the narrowly scoped privileged `cordium-storage` namespace.
  Its upstream chart source is pinned to the exact commit resolved by release
  tag `v0.0.36`; its provisioner and helper images are digest-pinned.
  Rancher's helper Pods require `hostPath` access while creating and removing
  volumes. The provisioner operates only on `zimaboard-1` under
  `/var/lib/cordium-workspaces`, where Cordium's rootless Podman runtime can
  enforce private ownership and mode bits that the QNAP NFS export cannot.

`cordium-local` is node-local scratch storage with a `Delete` reclaim policy.
It is not replicated or backed up and must not be used for durable app data.

The NAS-side setup is documented in `docs/storage-nfs.md`. Do not depend on
stateful workloads until the provisioner is healthy and the PVC write, delete,
and recreate validation in that runbook has passed.

The staged `renovate-cache-pv.yaml` declares only the cluster-scoped PV for a
separate QNAP cache volume. It stays outside this Kustomization until the
isolated export exists. Renovate's namespaced Argo project owns the matching
PVC and a read-only capacity probe after this platform PV reconciles.

`renovate-acceptance-ledger-platform.yaml` stages a separate static Talos-local
StorageClass and PV for the temporary private Renovate acceptance ledger on
`acer`. It is outside this Kustomization until a reviewed activation. The
Renovate Application owns only the matching namespaced claim after the platform
resources reconcile.
