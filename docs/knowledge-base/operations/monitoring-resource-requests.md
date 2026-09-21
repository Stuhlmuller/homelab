# Monitoring Resource Requests

Tags: #operations #monitoring #capacity

Status: rollout, initial acceptance, and sampled 24-hour follow-up passed.

Sources: `clusters/homelab/apps/prometheus/values.yaml`,
`clusters/homelab/apps/grafana/values.yaml`.

On 2026-09-07 at 03:02 UTC, authenticated Kubernetes inspection found no memory
requests on Prometheus, Grafana, Prometheus Operator, kube-state-metrics, or the
Prometheus and Alertmanager config reloaders. Prometheus alone used about
1 GiB. Scheduling these containers as if they needed zero memory permits
overpacking and leaves the affected Pods more exposed to memory-pressure
eviction, potentially removing alert evaluation during an incident.

Prometheus working-set observations informed these initial reservations:

| Container | 24-hour mean / maximum (MiB) | Retained seven-day maximum (MiB) | Memory request |
| --- | --- | --- | --- |
| Prometheus | 1034 / 1162 | 1183 | 1536Mi |
| Grafana | 311 / 425 | 760 | 768Mi |
| Prometheus Operator | 76 / 77 | 79 | 128Mi |
| kube-state-metrics | 82 / 86 | 86 | 128Mi |
| Prometheus config reloader | 15 / 18 | 19 | 32Mi |
| Alertmanager config reloader | 14 / 16 | 18 | 32Mi |

The seven-day query includes retained older Pods. Current Prometheus and
controller Pods had about 4.2 days of history; the current Grafana Pod had
about 1.6 days. Samples contain gaps, especially for reloaders, so maxima are
observed values, not proven bounds. Grafana's largest retained per-Pod p95
was about 485 MiB; its reservation leaves room above sustained usage while
preserving unrestricted bursts. No CPU setting or memory limit changes.
Alertmanager keeps its existing 200Mi request. PVCs, retention, and placement
rules remain unchanged.

The change adds 2624 MiB of scheduler reservations. Applying that delta to the
03:00 UTC placement gives about 11827 / 15261 MiB requested on `acer` and
4844 / 7282 MiB on `zimaboard-1`; the other workers receive no additional
reservation in this placement model. These are scheduling-fit calculations,
not a promise that the scheduler will retain those placements. The existing
`KubeMemoryOvercommit` calculation has a 3.30 GiB largest-node-loss shortfall;
honest requests increase that estimate to about 5.86 GiB. Additional capacity
and stateful recovery planning remain necessary; requests do not create RAM.

Before rollout, render the pinned charts and run the full static gate. After
Argo CD reconciles, verify both monitoring StatefulSets and the Grafana,
operator, and kube-state-metrics Deployments complete their rollouts, inspect
their admitted memory requests, and check for new Pending Pods or evictions.
Remeasure working sets after 24 hours and after any retention or scrape-volume
change. Reverting the values restores the prior reservations through GitOps;
it does not repair a real capacity deficit. The separate monitoring storage
migration proposal remains unchanged.

On 2026-09-07 at 03:34 UTC, both monitoring Applications were `Healthy` and
`Synced` at `05b9942f`. All five workloads were Ready with zero restarts on their
replacement Pods, and admitted requests matched the values above. Grafana and
Alertmanager ran on `acer`; Prometheus, its operator, and kube-state-metrics ran
on `zimaboard-1`. A 03:41 UTC query through the local Prometheus endpoint found
34 of 34 scrape targets up and all four nodes Ready.

The initial acceptance supplied placement evidence for the later CoreDNS
surge-capacity preflight. A read-only follow-up on 2026-09-12 at 01:08 UTC
completed the sampled 24-hour working-set observation:

| Container | 24-hour mean / maximum (MiB) | Admitted memory request |
| --- | --- | --- |
| Prometheus | 763.7 / 1009.3 | 1536Mi |
| Grafana | 288.2 / 290.8 | 768Mi |
| Prometheus Operator | 33.3 / 36.9 | 128Mi |
| kube-state-metrics | 38.3 / 43.5 | 128Mi |
| Prometheus config reloader | 18.7 / 24.3 | 32Mi |
| Alertmanager config reloader | 14.0 / 17.1 | 32Mi |

All 34 current scrape targets were up. The observed 24-hour series showed no
monitoring container restart, rule failure, or missed-evaluation increments,
and no node-pressure samples. Active Pods were Ready; no Warning events or
Evicted Pods remained in the current Kubernetes inventory. That inventory does
not prove the absence of historical evictions.

Container samples have gaps, with at least 4851 samples per observed series;
all four current cAdvisor targets use a 10-second interval. These maxima are
observed values, not hard bounds or proof of continuous collection. The
September 7 monitoring Pod identities and admitted requests were unchanged.
Keep the existing reservations; this observation does not resolve the
largest-node-loss capacity deficit or monitoring storage recovery work.
Queries and result receipts remain private.

## September 21 Memory Overcommit Incident

Status: partial remediation prepared; Dispatcharr and AFFiNE suspension selected.

Authenticated read-only inspection at approximately `2026-09-21T03:13Z`
reproduced `KubeMemoryOvercommit` firing, active since September 7. Prometheus
was `Healthy` and `Synced` at `9716e9d9` with chart `85.2.0`; the rule evaluated
successfully. All four nodes were Ready, with no MemoryPressure or Pending Pods.

| Quantity | GiB |
| --- | ---: |
| Active ordinary-container memory requests | 22.862 |
| Total allocatable memory | 30.402 |
| Largest node, `acer` | 14.903 |
| Capacity after largest-node loss | 15.499 |
| Node-loss shortfall | 7.363 |

The recording-rule total matched deduplicated requests for Running/Pending
Pods. Each node had one allocatable-memory series. Thus stale terminal Pods
and duplicate scrapes did not explain the alert. The seven-day request maximum,
sampled every five minutes, was 22.894 GiB. This is a failover-capacity warning,
not evidence of current memory pressure.

The chart's expression combines a non-HA total-capacity branch with an ungated
largest-node-loss branch. The `HA clusters` comment does not establish that
single-control-plane clusters should be exempt: upstream
[largest-node-loss rationale](https://github.com/kubernetes-sigs/kubernetes-mixin/pull/646)
applies to heterogeneous clusters, and the current implementation retains that
branch. Changing it would change availability policy without repairing the
documented deficit. Keep the alert enabled while reducing demand.

Rodman selected Dispatcharr and AFFiNE for suspension. Their combined 3.500 GiB
reduction projects requests of 19.362 GiB and a remaining 3.863 GiB node-loss
shortfall. Keep `KubeMemoryOvercommit` enabled; these two suspensions alone do
not clear it. Further workload selection or added capacity remains necessary.

Candidate savings below include running app containers and dedicated databases
at diagnosis, but exclude shared platform services and access proxies. Only the
two selected apps are configured for suspension; retain their PVCs.

| App | Current requests GiB |
| --- | ---: |
| OpenClaw | 2.063 |
| Dispatcharr and its PostgreSQL | 1.875 |
| AFFiNE, PostgreSQL, and Redis | 1.625 |
| Multica frontend, backend, and PostgreSQL | 1.500 |
| n8n and its PostgreSQL | 0.750 |
| OctoBot | 0.500 |
| NOFX frontend and backend | 0.313 |

Express selected suspensions in their repository-owned manifests/Helm values,
account for scheduled jobs and dependent services, and render before GitOps
rollout. Removing at least 7.363 GiB only satisfies the current alert arithmetic;
init containers, placement constraints, rollout demand, and underrequested
workloads still require headroom. Seven-day observed working sets exceeded
requests for the API server, n8n, OctoBot, and Deluge; reducing reservations
solely to clear the alert would conceal demand. Per-Pod observation windows
can be shorter than seven days and are not proven peak bounds.

For read-only verification, use the temporary local Prometheus port-forward
described in `clusters/homelab/apps/prometheus/README.md`, then query
`/api/v1/alerts` and `/api/v1/rules?type=alert`. Require exactly one healthy
`KubeMemoryOvercommit` rule still firing with approximately 3.863 GiB of
shortfall after these two suspensions. Require no pending/firing instance only
after further workload reduction or added capacity eliminates the shortfall.
Recheck the expression's request/capacity inputs, node readiness, pressure,
remaining workload health, and retained PVCs. No runtime changes were made
during diagnosis. Verify the selected suspension through Argo CD before marking
it applied; the remaining deficit must stay visible.

Before rollout, the full static gate and rendered Conftest policies passed.
Pinned Dispatcharr and Grafana charts rendered successfully; checks confirmed
five zero-replica workloads, app-before-database sync waves, and unchanged claim
definitions. Server-side dry-run diffs passed for both selected apps. Offline
Prometheus fixtures confirmed that the narrowed Grafana expression omits AFFiNE
while detecting missing probes for the other three databases. The committed
AFFiNE suspension probe check covers zero, nonzero, omitted, and invalid replica
values while retaining other app checks; shell/YAML/whitespace checks passed.

Separate monitoring follow-up: the existing Grafana PostgreSQL query returns
zero for its `increase(...) == 0` branch, while its threshold requires a value
greater than zero. Verify stalled-but-present probe series with a dedicated
fixture and correct that pre-existing detection gap separately; the missing
probe branch returns one and remains active.
