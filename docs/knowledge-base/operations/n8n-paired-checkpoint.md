# n8n Paired Checkpoint

The [operator runbook](../../n8n-paired-checkpoint.md) declares a manual cold
capture of the complete n8n instance tree and PostgreSQL 14 cluster. Both private
archives share one session and acceptance receipt. No live capture or full
application restore has been verified for this code yet.

- Existing n8n and n8n-postgres Applications, generated Terragrunt units,
  original state keys, images and claims retain ownership.
- Fixed stop/cold/capture/resume profiles are merged before the outage. The
  catalog guard blocks ordinary reconciliation while maintenance is active;
  the supported execution model is one serial operator with merges paused.
- Reader Pods run as the current source UIDs, mount sources read-only, and
  stream directly off NAS. No new PVC, source permission change, credential
  path, recurring schedule, automatic upload, pruning or restore is added.
- Clean container exit, PG shutdown state, live writer/node/claim identity,
  bounded observations, full archive reads, checksums and fsync precede receipt
  publication. Failures enter the existing-owner database-then-app resume path.
- A failed or interrupted session must be resumed, then replaced by a fresh
  session for a new capture. Never equate candidate files with an accepted pair.

Sources: `scripts/n8n-paired-checkpoint.py`,
`scripts/n8n-checkpoint-phase.py`, the `n8n-maintenance`,
`n8n-postgres-cold`, and `n8n-postgres-capture` overlays, and
`scripts/ci/n8n-paired-checkpoint-check.py`.

Related: [[architecture/storage-and-state]], [[workloads/inventory]].
