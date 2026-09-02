# Talos Control-Plane Maintenance

Tags: #runbook #talos #maintenance

Canonical runbook: [`docs/talos-control-plane-maintenance.md`](../../talos-control-plane-maintenance.md)

Render and validate Talos configuration before applying it. Use
`talosctl validate --mode metal --strict`, authenticated access after bootstrap,
and repository-owned patches for control-plane changes.
Emergency recovery does not permit live machineconfig edits followed by
backfilling; use the validated patch workflow first.
Remote `talosctl` will use owner-only Octelium TCP Service
`talos-api.homelab` after the control-plane `machine.certSANs` patch is applied
and the off-LAN check passes. Talos mutual TLS remains required. Until then,
direct-IP operations require the LAN or temporary Tailscale subnet route;
direct IP remains the LAN recovery path after cutover.

For remote ZimaBoard recovery, the canonical runbook maps each worker to its
Talos address and uses authenticated `talosctl reboot`; reboot one worker at a
time only from a healthy cluster, verify node and cluster-wide workload
readiness, and never fall back to `--insecure`.

The canonical runbook also owns the dated 2026-08-25 corrupt-object recovery.
That recovery is exact-key and snapshot-first, with a Talos snapshot-restore
rollback; do not generalize it into a routine etcd mutation path.

See [[../architecture/cluster-topology]] and [[validation]].
