# Descheduler Safety

The long-running Deployment evaluates eviction policy every 30 minutes through
`deschedulingInterval: 30m`. The chart's `schedule` setting applies only to
CronJobs and must not be set here. This is an interval from process execution,
not a wall-clock cron schedule; restarting the process resets its timing.

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

The cadence check also validates the rendered ConfigMap policy, including
plugin coverage and the existing eviction guards. After rollout, check private
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
