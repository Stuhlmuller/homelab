# Prometheus Storage Profile

Prometheus persists metrics and Alertmanager state on `nfs-default`.

- Backup: covered by the NFS backup gate in `docs/storage-nfs.md`.
- Restore: restore Prometheus and Alertmanager PVCs before relying on retained
  metrics.
- Rollback: preserve PVCs unless the operator accepts metrics loss.
