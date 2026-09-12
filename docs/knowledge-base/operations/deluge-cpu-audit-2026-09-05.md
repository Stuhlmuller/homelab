# Deluge CPU Audit — 2026-09-05

Status: diagnostic code prepared; rollout and profiling remain unverified.
Diagnosis is required before changing the VPN CPU cap.

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

## September 6 Recheck

At 20:39 UTC, mean CPU remained 298.7m over one hour and 299.8m over 24 hours.
The same Pod and pinned Gluetun image were Ready with no init-container restart
increase in that daily window. VPN and daemon health samples remained healthy;
the daemon reported 17 torrents and zero errors. One-hour `tun0` traffic averaged
50,381 bytes/s received and 5,059 bytes/s transmitted.

At 20:41 UTC, a read-only 26.11-second accounting sample measured 7.22 CPU seconds
in PID 1 (`gluetun-entrypo`), or 276.5m, versus 7.834 CPU seconds in its container
cgroup, or 300.0m. The process accounted for approximately 92% of consumed CPU:
3.86 seconds in user mode and 3.36 in system mode, using verified `CLK_TCK=100`.
Pod UID, container identity, process start time, and restart count stayed stable.
Sequential reads, health probes, and diagnostic overhead limit exact attribution.
This supports profiling the Go process; it does not establish its busy function
or demonstrate a current functional outage.

## Next Step

Keep the 300m cap while identifying the busy path. The diagnostic change enables
Gluetun's existing pprof listener on loopback only, supplies a bounded private
capture helper, and documents disabling it afterward. Profiling is disabled
in the upstream image by default. Although the Go fallback is `localhost:6060`, the pinned
[image Dockerfile](https://github.com/passteque/gluetun/blob/v3.41.3/Dockerfile#L221-L224)
overrides its address to `:6060`. Explicitly set `127.0.0.1:6060` when enabling
profiling; enabling the flag alone would bind a wildcard listener.

The pinned [file reader](https://github.com/passteque/gluetun/blob/v3.41.3/internal/configuration/sources/files/reader.go)
supports committed `/gluetun/pprof_enabled` and
`/gluetun/pprof_http_server_address` inputs ahead of the image environment.
The app chart mounts those individual files read-only from its ConfigMap
only into Gluetun. Block and mutex profiling remain disabled. No Service,
ingress, firewall change, or additional capability is needed. Capture through
a loopback-only operator port-forward, with a bounded duration and private
output outside the public repository.

Profiling starts with the process: activation and removal each require a
reviewed Recreate rollout. Verify VPN/Deluge health and recurrence of sustained
CPU saturation before interpreting a profile, since a restart may change the
busy condition. Confirm listener removal afterward. The chart's ConfigMap
checksum triggers rollout when the committed enabled value changes; individual
subPath mounts do not refresh in place. See the app README for the helper's
`check`, `capture`, and `check-disabled` commands and health/backup gates.
No diagnostic rollout or profile collection has been performed.

If profiling shows useful work is quota-limited, compare a small declarative
limit change against the same CPU, packet-rate, VPN-health, and node-headroom
windows. Revert if CPU grows without a health or throughput benefit. Do not
remove the limit or increase the request solely from throttled-period percentage.
This diagnostic keeps the existing `media/deluge` ownership. Reconcile its
namespace assumptions if the separate namespace-isolation PR #829 is adopted.

## Validation

Rendering with Helm 3.20.2 and exact app-template 4.4.0 adds only ConfigMap
`media/deluge`, its volume, the two Gluetun-only read-only file mounts, and the
Pod checksum. Prior resources, networking, probes, storage, security settings,
and limits compare unchanged. Rendering `"off"` changes only the ConfigMap's
enabled value and checksum. The proposed ConfigMap name was absent from the
live namespace at preflight.

Eleven offline helper tests cover endpoint/TLS fences, ownership/identity races,
loopback-only sockets, committed config, private files, idempotent cleanup,
HTTP deadlines, and complete gzip/CRC
validation under compressed and expanded size bounds. These synthetic cases
do not validate the live Gluetun listener, profiling overhead, or the CPU cause.

See [[audit-2026-09-04]] and [[continuous-improvement]].
