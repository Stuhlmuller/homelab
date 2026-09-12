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
- Resume uses a documented temporary pin to the prepared commit SHA without an
  operator GitHub fetch. Service retains its maintenance markers until separate
  `unpin` verifies reachable, unchanged n8n sources, checkpoint scripts and the
  full IaC tree before restoring `main`; changed definitions leave service pinned.
- Timed-out or interrupted commands terminate their owned process groups before
  recovery starts; failed cleanup blocks automatic resume.
- Resume and unpin receipts require both original workloads ready and their
  Applications reconciled, including retries whose markers already read normal.
- A failed or interrupted session must be resumed and unpinned, then replaced
  by a fresh session for a new capture. Never equate candidate files with an
  accepted pair.

Sources: `scripts/n8n-paired-checkpoint.py`,
`scripts/n8n-checkpoint-phase.py`, the `n8n-maintenance`,
`n8n-postgres-cold`, and `n8n-postgres-capture` overlays, and
`scripts/ci/n8n-paired-checkpoint-check.py`.

Related: [[architecture/storage-and-state]], [[workloads/inventory]].
