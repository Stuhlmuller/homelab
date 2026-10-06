# OpenClaw Runtime State

Tags: #operations #openclaw #storage

Configuration, workspace, archived transcripts and recovery archives use the
retained `openclaw` NFS claim. Global state, agent SQLite databases and native
Codex state use retained local volumes on `zimaboard-1`. Platform storage owns
the StorageClass and PVs; the OpenClaw application owns the namespaced PVCs.
Local WAL state survives Pod replacement, but has no automatic node failover.
Daily online SQLite backups retain seven snapshots on NFS. Node-disk loss needs
a verified snapshot restore and can lose writes since the last backup.

## Direct Mount Identity

Talos kubelet mount namespaces can expose empty overlay directories through
`subPath` even when a host directory contains valid databases. Direct child PVs
mount the existing host directories without `subPath`; bootstrap requires parent
and child views to identify the same database inodes before starting a CLI.
Missing local databases stop startup and require reviewed restoration. Never
silently refill current state from stale NAS data.

The current bootstrap verifies its versioned offline backup, runtime database
integrity and mount identity before applying configuration. Existing archives
remain private recovery data. A shared UID-private Pod-local coordinator volume
keeps identity locks off NFS; single-replica `Recreate` and same-Pod writer
ownership remain required.

Source: [OpenClaw runbook](../../../clusters/homelab/apps/openclaw/README.md).
See [[openclaw-bootstrap-batching]] for startup timing and configuration gates,
[[openclaw-personal-assistant]] for assistant behavior, and
[[../architecture/storage-and-state]] for backup limits.
