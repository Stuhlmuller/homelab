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

On 2026-10-06, cleanup-triggered cold starts passed init, database-integrity
and mount-identity gates, but native model-runtime publication repeatedly hit
its 120-second agent-facts deadline during event-loop stalls. The rollout
investigation recorded about 2 GB read and 897 MB written for roughly 204 MB
of databases, including synchronous SQLite snapshot staging. Image and resource
limits were unchanged, configuration was valid, and removed migration guards
had already completed. A retained Codex migration warning coexisted with the
failure; causality is unproven.

The same investigation verified that `/home/node/.cache/openclaw` readonly-v2
snapshots use container overlay, not NFS. Canonical shared and agent databases
use local XFS on `/dev/mmcblk0p4`; only the `/data` root is NFS. Moving that
snapshot cache to `emptyDir` has no demonstrated NFS benefit; no filesystem
change is proposed on this evidence.

Separately, Kubernetes events record two startup-probe kills; one app attempt
ran from 05:09:10 to 05:15:10 UTC before exit 137. The declared startup budget
is now 900 seconds instead of six minutes; readiness and liveness are unchanged.
This removes that premature termination boundary, not the native timeout.
Require actual gateway responsiveness and Pod readiness after deployment.

Source: [OpenClaw runbook](../../../clusters/homelab/apps/openclaw/README.md).
See [[openclaw-bootstrap-batching]] for startup timing and configuration gates,
[[openclaw-personal-assistant]] for assistant behavior, and
[[../architecture/storage-and-state]] for backup limits.
