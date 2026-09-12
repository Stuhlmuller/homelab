# Deluge CPU Audit — 2026-09-05

Status: observed; diagnosis required before changing the VPN CPU cap.

Source: `clusters/homelab/apps/deluge/values.yaml`, read-only Kubernetes and
Prometheus inspection on September 5 Pacific / September 6 UTC.

## Finding

Gluetun's 300m CPU limit is continuously binding. This is more than a high
throttled-period percentage, but a higher limit is not yet a proven throughput
fix. The CPU shift followed a container restart without corresponding traffic
growth.

| Window | Mean CPU | 95th percentile CPU |
| --- | ---: | ---: |
| 1 hour | 300m | 300m |
| 6 hours | 299m | 300m |
| 24 hours | 299m | 300m |
| 7 days | 96m | 300m |

The sidecar restarted at `2026-09-04T07:56:48Z`; the first hourly sample above
285m was at `2026-09-04T08:15:21Z`. Every hourly sample in the latest daily window,
ending `2026-09-06T02:15:21Z`, exceeded that threshold. The earlier 24-hour window
offset by 48 hours averaged about 25m. Combined tunnel receive/transmit traffic
averaged 55.2 kB/s in the latest daily window versus 56.6 kB/s in the preceding
window; the current combined rate was about 89 packets/s. Startup logs confirm
kernel WireGuard. These observations
support investigating a process CPU regression; they do not identify its cause.
The retained logs showed no VPN restart loop or error burst.

The throttled-period ratio was approximately 100% over the latest daily window.
Throttled-seconds metrics are not collected, so lost CPU time cannot be inferred
from that ratio. Gluetun is a restartable init container: inspect
`initContainerStatuses` and `kube_pod_init_container_status_restarts_total`, not
only regular container restart metrics.

## Capacity and Health

`zimaboard-0` had 3,950m allocatable CPU and 3,395m requested, leaving 555m
unreserved. A node usage snapshot was about 1,668m. Regular and restartable-init
workload CPU averaged 1.17 cores over 24 hours, with a 1.19-core 95th percentile;
these container totals exclude host overhead. Sustained host CPU/idle metrics
were unavailable, so the snapshot does not establish durable node or N-1
headroom. The existing capacity work remains under #785.

Deluge RPC stayed healthy through the daily window. VPN health was approximately
99.84%, with isolated readiness failures but no liveness failures or container
restart during that window; the Pod stayed Ready. Current Gluetun healthcheck
passed. This is an efficiency and intermittent-health finding, not a demonstrated
Deluge outage.

## Next Step

Keep the 300m cap while identifying the busy path. A future reviewed diagnostic
change can enable Gluetun's existing pprof listener on localhost only, collect
a bounded private CPU profile, and disable it afterward. The pinned release's
[profiling defaults](https://github.com/passteque/gluetun/blob/v3.41.3/internal/pprof/settings.go)
disable profiling and default its listener to `localhost:6060`; no profiling
configuration is currently declared. Profiles and raw diagnostics must stay
outside the public repository. No diagnostic rollout or profile collection was
performed during this audit.

If profiling shows useful work is quota-limited, compare a small declarative
limit change against the same CPU, packet-rate, VPN-health, and node-headroom
windows. Revert if CPU grows without a health or throughput benefit. Do not
remove the limit or increase the request solely from throttled-period percentage.
No CPU-specific open PR was found; coordinate future manifest edits with the
existing Deluge namespace-isolation PR #829 rather than duplicating its cutover.

See [[audit-2026-09-04]] and [[continuous-improvement]].
