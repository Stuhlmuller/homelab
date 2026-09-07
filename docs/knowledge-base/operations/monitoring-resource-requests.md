# Monitoring Resource Requests

Tags: #operations #monitoring #capacity

Status: rollout and initial acceptance passed; 24-hour observation pending.

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

This initial acceptance supplies current placement evidence for the CoreDNS
surge-capacity preflight; it does not complete the 24-hour working-set and
eviction observation. Recheck current headroom before the DNS rollout.
