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
UID-and-node-bound exact allowlist at every step; any missing, stale,
duplicate, or unlisted entry stops the sequence. A fixed worker-name mapping
and fail-closed checks require every non-dashboard Talos service to report
running and healthy before reboot. This exception does not apply to unrelated
degraded workloads.

The 2026-09-02 issuer incident has a narrower stalled-worker recovery. Stale
CNI authentication caused Pod churn, then memory, eMMC, and NFS pressure wedged
the `zimaboard-1` kubelet. `zimaboard-2` showed severe pressure and a concurrent
kubelet stall, but its exact cause is unverified. Acer and `zimaboard-0` stayed
healthy. Because API-deleted NFS Pods may still execute, the worker reboot is
writer fencing. After validating the healthy cluster, preserve but stop the
known Cordium Workspace `v64` through its native lifecycle API; `ws-v64` is its
generated Kubernetes name. Reject an ephemeral Workspace, prove the exact PVC
remains bound, require its ConfigMap, Service, and Deployment to disappear,
and allow only zero-replica controller remnants or deleting Pods. Then recover
`zimaboard-1` once and require a new boot ID, fresh lease, healthy services and
Pods, no fresh issuer errors, and 31 clean one-minute pressure samples before
recovering `zimaboard-2`. A timeout permits physical power only
after the same boot ID and healthy remainder of the cluster are revalidated;
never submit a second remote reboot. Keep `zimaboard-0` running when healthy.
The required 30-minute soak checks each minute for over 20% available memory,
no blocked processes, less than 1% full memory or I/O stall time over avg60,
no Pod replacement, container-set change, restart or OOM growth, and no active
Cordium workspace on `zimaboard-1`. This duration covers the incident's
observed 18–30 minute failure lag.

Capacity follow-up is required after recovery. `zimaboard-1` scheduled requests
were 82% of allocatable memory but limits were 627%; OpenClaw and the active
Cordium workspace alone could exceed node capacity, while Octelium Enterprise
used several 5 MiB or empty requests. `zimaboard-2` ran BestEffort Prometheus
and Argo CD components on 1.28 GiB allocatable memory. Measure recovered usage,
then correct requests, limits, or capacity in
[`openclaw/values.yaml`](../../../clusters/homelab/apps/openclaw/values.yaml),
[`octelium-enterprise/resources.yaml`](../../../clusters/homelab/apps/octelium-enterprise/resources.yaml),
[`prometheus/values.yaml`](../../../clusters/homelab/apps/prometheus/values.yaml),
and the
[`bootstrap-argocd` unit](../../../IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl).
Do not invent limits while metrics are unavailable.

The canonical runbook also owns the dated 2026-08-25 corrupt-object recovery.
That recovery is exact-key and snapshot-first, with a Talos snapshot-restore
rollback; do not generalize it into a routine etcd mutation path.

See [[../architecture/cluster-topology]] and [[validation]].
