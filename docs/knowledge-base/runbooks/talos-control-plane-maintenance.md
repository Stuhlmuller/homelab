# Talos Control-Plane Maintenance

Tags: #runbook #talos #maintenance

Canonical runbook: [`docs/talos-control-plane-maintenance.md`](../../talos-control-plane-maintenance.md)

Render and validate Talos configuration before applying it. Use
`talosctl validate --mode metal --strict`, authenticated access after bootstrap,
and repository-owned patches for control-plane changes.

The canonical runbook also owns the dated 2026-08-25 corrupt-object recovery.
That recovery is exact-key and snapshot-first, with a Talos snapshot-restore
rollback; do not generalize it into a routine etcd mutation path.

See [[../architecture/cluster-topology]] and [[validation]].
