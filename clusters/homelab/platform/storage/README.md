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

The local-path helper uses the cataloged Wolfi base with packaged BusyBox
instead of the standalone BusyBox image. Wolfi retains an APK package
database. On 2026-11-02, native Trivy 0.72.0 found 19 packages, including
BusyBox `1.38.0-r3`, in each pinned Linux child. The scanner reported zero
findings on amd64 and arm64 using the public database updated at 01:14 UTC
that day. The old standalone helper exposed only a container-root SBOM entry.
The [scan receipt](../../../../docs/evidence/cordium-helper-package-coverage-2026-11-02.json)
binds both reports to the immutable children and database revision.

Wolfi base preserves the helper's UID 0 default and `/bin/sh`, `mkdir`, and
`rm` applets. The chart runs `mkdir -m 0777 -p "$VOL_DIR"` during setup and
`rm -rf "$VOL_DIR"` during teardown. The controller's non-root security context
does not apply to these helper Pods. Chainguard's BusyBox-only image defaults
to UID 65532, so it would change host-path permissions behavior. Chart source,
controller image, helper resources, node placement, and reclaim policy remain
unchanged.

The result covers these two children at the recorded database revision.
Merge the catalog prerequisite and require successful protected `chainguard`
publication and authenticated pulls of this index before rollout. Recheck
both child reports against a current database. On Harbor, require a fresh
successful vulnerability scan with zero reported findings and a native,
package-bearing SBOM whose OCI subject matches each exact mirror child. Then verify Argo
reconciliation and the local PVC create, write, delete, and recreate behavior.
Local verification rendered the pinned chart and inspected both native image
filesystems; no Linux container runtime was available to execute the scripts.
Rollback restores the prior helper pin through GitOps without moving or
recreating existing volumes. Retain its catalog entry until rollout acceptance.

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

`renovate-cache-local.yaml` owns the active static `renovate-cache-local`
StorageClass and retained PV, explicitly bound to Renovate's same-named claim
in `automation`. It uses `/var/lib/renovate-cache` on `acer`'s Talos
`EPHEMERAL` filesystem. The advertised 20 GiB is not a quota or reservation;
node loss can lose the rebuildable cache. Renovate's credential-free init
container sets only the mount root's ownership before the non-root runner
starts. The old NFS cache and staged dedicated NAS resources remain intact.
