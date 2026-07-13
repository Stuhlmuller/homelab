# Talos Control-Plane Maintenance

Tags: #runbook #talos #maintenance

Canonical runbook: [`docs/talos-control-plane-maintenance.md`](../../talos-control-plane-maintenance.md)

Render and validate Talos configuration before applying it. Use
`talosctl validate --mode metal --strict`, authenticated access after bootstrap,
and repository-owned patches for control-plane changes.

See [[../architecture/cluster-topology]] and [[validation]].
