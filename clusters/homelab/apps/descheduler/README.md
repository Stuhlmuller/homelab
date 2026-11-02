# Descheduler Safety

The long-running Deployment evaluates eviction policy every 30 minutes through
`deschedulingInterval: 30m`. The chart's `schedule` setting applies only to
CronJobs and must not be set here. This is an interval from process execution,
not a wall-clock cron schedule; restarting the process resets its timing.

The first policy is intentionally conservative:

- Do not evict system-critical pods.
- Ignore pods with PVCs.
- Require at least two replicas before eviction.
- Start with balancing and anti-affinity cleanup only.

Expand the policy only in a follow-up PR with live validation evidence.

Run `bash scripts/ci/descheduler-cadence-check.sh` to verify the pinned chart
renders `--descheduling-interval=30m`. After Argo CD reconciles the reviewed
revision, inspect the live Deployment argument and observe at least two cycles
in private logs to confirm the expected cadence. Do not restart it manually.
Rollback through a reviewed values revert; the previous omitted interval used
the chart default of five minutes.
