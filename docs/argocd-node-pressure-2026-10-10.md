# Argo CD Reconciliation Stall: 2026-10-10

`zimaboard-2` temporarily lost kubelet health during the rollout of
[cleanup PR #1251](https://github.com/Stuhlmuller/homelab/pull/1251).
`argocd-application-controller-0` on that node stopped reconciling. Automatic
eviction and replacement restored reconciliation; no manual mutation, restart,
reboot, force-deletion, or sync was performed.

## Evidence

Read-only observations; all times UTC on 2026-10-10.

| Time | Observation |
| --- | --- |
| 22:28:46 | Last recorded `zimaboard-2` kubelet heartbeat. |
| 22:31:03 | Last recorded Argo CD reconciliation before the stall. |
| 22:31:28 | Cleanup PR #1251 merged, after the last recorded kubelet heartbeat. |
| 22:31:51 | Node Ready became `Unknown`, reason `NodeStatusUnknown`. |
| Around 22:36 | Kubelet `10.1.0.202:10250` timed out during TLS handshake. Authenticated Talos API remained reachable on Talos `v1.11.3`; kubelet was running but unhealthy. |
| Around 22:36 | `MemTotal=1835116 kB`, `MemAvailable=137448 kB` (about 7.5%). Kernel PSI `full avg60`: memory **36.23%**, I/O **65.54%**. |
| 22:38:19 | Replacement `argocd-application-controller-0` created and scheduled on `zimaboard-1`. |
| 22:38:20 | `zimaboard-2` returned to Ready. |
| 22:38:34 | Replacement controller became Ready. |

The low available memory and sustained memory/I/O stalls support a resource
stall hypothesis. The exact cause remains unproven; these samples do not
establish an OOM, a storage fault, or a particular workload as the cause.

The node also hosted `automation/n8n-postgres-0` with PVC
`data-n8n-postgres-0`. Writer-fencing safeguards were preserved: no Pod or PVC
was force-deleted or moved manually. The
[PostgreSQL contract](../clusters/homelab/apps/n8n-postgres/README.md)
uses NFS-backed state; an unreachable kubelet is not proof that its database
writer has stopped.

## Rollout Outcome

At 22:43 UTC, after controller recovery, all four affected Applications observed merge
`31245542329cb3f74709356c755b3264683e1ef4`. Grafana was healthy. OpenClaw was
still progressing through its normal long bootstrap at this observation;
application readiness was not yet established.

Earlier `Healthy`/`Synced` values were stale controller observations, not proof
that the merge had deployed. Acceptance requires a fresh reconciliation and
the expected source revision, followed by live workload readiness and the
relevant behavior checks in the [validation runbook](validation-runbook.md).

## Remaining Capacity Risk

Natural recovery did not resolve the underlying capacity question. Follow-up
must use reviewed repository desired state:

1. Compare worker memory, PSI, kubelet health, restarts/OOM events, and NFS
   latency over a sustained observation window. Reuse the read-only pressure
   sampling in the [Talos maintenance runbook](talos-control-plane-maintenance.md#degraded-recovery-issuer-cutover-resource-stall);
   this incident does not authorize its dated recovery mutations.
2. Review actual controller placement and workload memory budgets against the
   [Argo CD catalog unit](../IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl),
   which already declares two controller replicas. Propose any resource or
   scheduling changes there, validate the plan, and deliver through the
   [declared bootstrap path](argocd-bootstrap.md).
3. Review [Argo CD alert coverage](../clusters/homelab/apps/prometheus/argocd-prometheusrules.yaml)
   for stale reconciliation and node-pressure visibility. Add and validate any
   missing signals through a reviewed PR; retain revision and live-readiness
   checks even when reported Application health is green.
