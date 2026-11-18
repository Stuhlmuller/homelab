# Descheduler Safety

The active design is a long-running Deployment that evaluates eviction policy
every 30 minutes through `deschedulingInterval: 30m`. Stage one suspends the
chart as a CronJob so the repaired policy cannot start evictions. After a
separate protected activation, the Deployment interval resumes from process
start rather than a wall-clock cron schedule.

The first policy is intentionally conservative:

- Do not evict system-critical pods.
- Ignore pods with PVCs.
- Require at least two replicas before eviction.
- Check that a Pod fits another node before eviction (`nodeFit: true`).
- Evict at most one Pod across both strategies per cycle.
- Start with balancing and anti-affinity cleanup only.

Expand the policy only in a follow-up PR with live validation evidence.

Every enabled strategy needs a `pluginConfig` entry. Without it, Descheduler
v0.33.0 rejects the entire `conservative` profile even while the Pod stays
Ready and Argo CD reports Healthy. The anti-affinity strategy needs no extra
arguments. `LowNodeUtilization` uses the pinned chart's defaults: CPU, memory
and pod thresholds of 20%, with target thresholds of 50%. These compare
resource requests and pod counts against node capacity, not observed CPU or
memory consumption. Both maps must be nonempty, cover the same resources and
use percentages between 0 and 100, with each lower threshold at most its target.
See the pinned [chart defaults][defaults] and [argument validation][validation].

`DefaultEvictor.nodeFit` defaults to false in v0.33.0. Enabling it makes both
strategies check another node's selectors, taints, requested resources and
anti-affinity before eviction. This uses a [subset of scheduler checks][node-fit];
it does not establish physical memory headroom or reserve future CronJob demand.
`maxNoOfPodsToEvictTotal: 1` limits each cycle across both strategies so several
individually fitting Pods cannot be evicted together against the same spare
capacity. Physical headroom and recurring demand require separate executable
checks.

The repaired profile is staged as a suspended CronJob. Its Argo values source is
pinned to the pre-repair commit `934770124f6e3b3c1b0857ce8e510e0ea7a1e894`,
whose old profile cannot construct the enabled strategies. The chart source
also forces `kind=CronJob` and `suspend=true`, so the pinned old values cannot
leave a running Pod. The pinned chart renders one suspended CronJob and no
Deployment in both source paths. Its `replicas: 0` value is insufficient:
chart 0.33.0 renders a Deployment with one replica for zero. The protected PR
gate rejects an active kind, a moved values pin, or removal of the suspension
override. After protected delivery, verify Argo reports zero live Descheduler Pods.
This stage does not activate eviction.

Activation requires two separate protected changes. First, pin the Argo values
source to this stage's actual squash-merge commit after verifying its zero
Pods live. Then prepare a separate activation revision in Deployment mode
while Argo still reads the suspended commit. A repo-owned protected manual
workflow must bind the exact activation revision, collect fresh capacity
evidence immediately before changing the Argo source pin, and stop on changed
nodes, Pods, leases, Jobs, or stale timestamps. A PR-only capacity result is
insufficient because Argo tracks desired state after the merge. Do not merge
the activation revision or move the pin until that protected workflow exists
and its denial cases pass.

The prepared `collect_live_capacity_evidence` helper requires four nodes with fresh
healthy conditions and leases, complete inventories and settled Ready Pods.
It reserves the largest single movable Pod plus recurring Job demand against
both scheduling requests and fresh kubelet available memory on every possible
destination. Explicit container memory limits bound physical demand; unknown
limits, unsupported placement and overlapping Jobs fail closed. Existing Job
memory is credited once using UID-bound measurements; active old Job templates
remain reserved after a CronJob moves or suspends.

The capacity helper does not implement Kubernetes scheduling: native
NodeFit still owns its placement checks. It does not prove N-1 capacity or
future workload growth. It reads cluster state only, prints fixed status text,
and grants no new access. A denied kubelet-summary read fails the gate.
After a failed check, repair the owning desired-state contract and rerun; do
not waive missing measurements or treat zero requests as zero physical demand.

The staging check validates the rendered suspended CronJob and
ConfigMap policy, including plugin coverage and the existing eviction guards.
After the separate protected activation, check private
logs for successful profile initialization and complete cycles without
`unable to create a profile` or plugin configuration errors. Zero evictions
can be correct when no eligible violations exist; a Ready Pod alone is not
proof that policy evaluation works. This repair makes the previously inert
declared strategies operational; it enables no additional strategy.

Run `bash scripts/ci/descheduler-cadence-check.sh` to verify the pinned chart
renders `--descheduling-interval=30m`. After Argo CD reconciles the reviewed
revision, inspect the live Deployment argument and observe at least two cycles
in private logs to confirm the expected cadence. Do not restart it manually.
Rollback through a reviewed values revert; the previous omitted interval used
the chart default of five minutes.

[defaults]: https://github.com/kubernetes-sigs/descheduler/blob/v0.33.0/charts/descheduler/values.yaml#L125-L136
[validation]: https://github.com/kubernetes-sigs/descheduler/blob/v0.33.0/pkg/framework/plugins/nodeutilization/validation.go
[node-fit]: https://github.com/kubernetes-sigs/descheduler/blob/v0.33.0/pkg/descheduler/node/node.go
