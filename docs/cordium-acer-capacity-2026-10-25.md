# Acer capacity for one Cordium workspace

PR #1330's changes are already live. New workloads consumed the released space:
on October 25 Acer requested 14,099 MiB of 15,260.7 MiB allocatable. The
[seven-day measurement receipt](evidence/acer-cordium-capacity-2026-10-25.json)
records this follow-up preparation, not a completed rollout.

Move four stateless controllers to `zimaboard-1`: descheduler, metrics-server,
kube-state-metrics and the Kiali operator. Their summed seven-day peak working
sets were 397.4 MiB; the worker had 2,078 MiB available. The operator's old
64 MiB request was below its 250.9 MiB peak, so reserve 384 MiB there. The other
three reservations stay unchanged. This leaves about 1,681 MiB available even
using all four observed peaks together. It does not move the Kiali operand.

Keep Alertmanager and LiteLLM PostgreSQL explicitly on Acer. Change only these
memory requests; all memory limits, CPU requests, replicas and volumes remain:

| Container | Before | After | Seven-day peak |
| --- | ---: | ---: | ---: |
| Alertmanager | 200 MiB | 64 MiB | 37.7 MiB |
| LiteLLM PostgreSQL | 256 MiB | 128 MiB | 46.9 MiB |
| Dispatcharr app | 1,024 MiB | 896 MiB | 610.2 MiB |
| Dispatcharr Celery | 512 MiB | 448 MiB | 341.3 MiB |
| Dispatcharr Redis | 128 MiB | 64 MiB | 7.4 MiB |

The plan releases 1,168 MiB of Acer requests. Expected headroom is 2,329.7 MiB;
one 2 GiB workspace plus the 8 MiB sysctl Pod leaves 273.7 MiB before any other
new controller/DaemonSet overhead. Lower reservations do not release the same
amount of physical RAM. Fresh observations and the limits below govern execution.

## Delivery and acceptance

Use protected merge. Argo CD follows the updated values; reconcile only the
`metrics-server` Application registration with the exact-main targeted Terragrunt
Apply because its inline Helm inputs changed. Do not use a full apply for this
change. Expect normal controller rollovers and brief Alertmanager/PostgreSQL
Pod replacement; require SQL/app recovery before accepting the rollout.

Verify all four controllers are Ready on `zimaboard-1`, the Kiali operand is
healthy, metrics API queries work, Alertmanager remains on Acer, PostgreSQL is
ready, and Dispatcharr is ready. Require no node memory pressure, at least
1,536 MiB available worker memory after the moves, and at least 3,072 MiB
available Acer memory before creating a workspace. Recheck actual reservations;
refuse a test if 2 GiB plus new Pod overhead cannot schedule.

The patched generator must hard-pin ephemeral workspaces to Acer. Do not allow
new worker reservations to attract the test to the other node. The original six
stopped workspaces are non-ephemeral; preserve their native inventory and bound
PV/PVC identities. Node namespace mappings, Acer eligibility, local storage and
the published controller must pass their own prerequisites before startup.

Run one bounded smoke with a startup deadline, private diagnostics and reserved
cleanup time. Stop on node pressure, verify native deletion and every owned
Kubernetes child is absent, and compare all six original storage identities.
No runner cutover follows merely from a successful scheduler placement.

Rollback first removes the exact owned smoke through its native cleanup path,
then restores source configuration through protected delivery. Recheck capacity
before returning controllers to Acer; preserve all volumes. Crossplane stays in
its already-deployed standby state.

## Current rollout hold

A later October 25 read-only check found only 1,334.7 MiB available on
`zimaboard-1` while its regular Renovate job was active. This is below the
1,536 MiB minimum even before moving the four controllers. PR #1656 remains
draft; do not apply this placement proposal. Require fresh evidence that the
destination retains the reserve during regular workloads, or revise placement
and reservations. An idle interval alone does not establish steady-state capacity.
