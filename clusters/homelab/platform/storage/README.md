# Platform Storage

This path owns only the default NFS StorageClass desired state. It does not
install, replace, or own the NFS provisioner.

Read-only inspection on 2026-05-24 found no existing StorageClass, no CSI
driver, and no NFS provisioner in the inspected cluster. The
`default-nfs-storageclass.yaml` file therefore uses public-safe placeholder
values and is a rollout blocker until the actual existing provisioner is
available and documented in `docs/storage-nfs.md`.

Do not sync the `platform-storage` Argo CD Application until the placeholder
server/share values have been replaced or externalized safely.

