# Platform Storage

This path owns the QNAP-backed NFS dynamic provisioner for the homelab cluster.
The parent `platform-storage` Application is registered by the Terragrunt unit
at `IaC/live/argocd-apps/platform-storage` and is automated by default. It
creates the child `nfs-subdir-external-provisioner` Application in the `argocd`
namespace. The child Application installs the upstream Helm chart into the
`storage` namespace and creates the default `nfs-default` StorageClass.

The NAS-side setup is documented in `docs/storage-nfs.md`. Do not depend on
stateful workloads until the provisioner is healthy and the PVC write, delete,
and recreate validation in that runbook has passed.
