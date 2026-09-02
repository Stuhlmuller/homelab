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
The control-plane issuer cutover also requires an explicit all-node Ready wait
before rebooting the sole control-plane node.
After Acer returns, defer the global Pod gate only for verified old-issuer CNI
failures: reboot `zimaboard-2`, `zimaboard-1`, then `zimaboard-0`, require
target-local Pod readiness after each, and restore the global gate after the
last worker. Before each reboot, require the full node/Talos/etcd preflight and
allowlist every unready Pod only after its failure is positively traced to an
old-issuer CNI authorization error on an unrebooted worker. Rebuild the
exact allowlist at every step; any missing, stale, duplicate, or unlisted entry
stops the sequence. A fixed worker-name mapping and fail-closed checks require
every non-dashboard Talos service to report running and healthy before reboot.
This exception does not apply to unrelated degraded workloads.

The canonical runbook also owns the dated 2026-08-25 corrupt-object recovery.
That recovery is exact-key and snapshot-first, with a Talos snapshot-restore
rollback; do not generalize it into a routine etcd mutation path.

See [[../architecture/cluster-topology]] and [[validation]].
