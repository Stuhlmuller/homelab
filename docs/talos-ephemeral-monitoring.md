# Talos EPHEMERAL filesystem monitoring

The authenticated kubelet cAdvisor scrape supplies capacity, usage, free inodes
and total inodes for the Talos `/var` filesystem. This filesystem holds retained
local volumes as well as images and kubelet data. Prometheus compares each
node with its own capacity. Grafana's **Homelab Overview** shows free bytes,
free inodes and estimated hours until full.

| Node | `MountStatus` target | EPHEMERAL partition |
| --- | --- | --- |
| `acer` | `/var` | `/dev/sda4` |
| `zimaboard-0`, `zimaboard-1`, `zimaboard-2` | `/var` | `/dev/mmcblk0p4` |

These mappings are specific to this homelab. On November 2, 2026, authenticated
Talos `VolumeStatus` and `MountStatus` resources confirmed them on all four
nodes. At 06:53 UTC, direct kubelet reads returned all four fresh gauges on
each mapped partition, including the recovered `zimaboard-2`. Add the mapping
and expected-node alert when another node becomes
eligible for local state. Reconfirm the mapping after a disk replacement or
repartition:

```sh
talosctl --nodes <node-IP> get volumestatus EPHEMERAL -o yaml
talosctl --nodes <node-IP> get mountstatus -o yaml
```

Require the mounted `/var` source to match the EPHEMERAL volume location and
the Prometheus `device` label. The chart's cAdvisor filter adds
`homelab_talos_volume="EPHEMERAL"` only for the mapped root (`id="/"`) with an
empty Pod label. Container filesystems and sandbox mounts continue through the
chart's existing filters. Free bytes are filesystem capacity minus usage;
writer quotas, reserved blocks, and concurrent use can reduce usable space.

## Thresholds and response

The rules use kube-prometheus-stack 85.2.0's node-filesystem thresholds. The
forecast divides current free capacity by its measured rate of loss over six
hours. It requires at least 60 of 72 five-minute capacity samples and a falling
trend. Rapid workload changes can shorten the actual window.

| Alert | Warning | Critical |
| --- | --- | --- |
| `TalosEphemeralFillingUp` for 1h | Under 15% bytes or 40% inodes free and under 24h forecast for that resource | Under 10% bytes or 20% inodes free and under 4h forecast for that resource |
| `TalosEphemeralAlmostFull` for 30m | Under 5% bytes or inodes free | Under 3% bytes or inodes free |
| `TalosEphemeralTelemetryMissing` for 15m | An expected node lacks a valid pair of byte and inode readings | — |

A critical filesystem alert inhibits its warning only for the same node, device
and resource. Byte and inode warnings on other filesystems continue to route.

For a capacity alert, check its `node`, `device`, and `resource`. Read the
three dashboard panels alongside workload growth and recent deployment times.
Verify backups, map the retained PVs and host paths to their owners, and plan
an application-specific cleanup, capacity expansion or migration through
reviewed GitOps. Preserve bound claims and data. A proposed migration also
needs enough measured space for simultaneous copies and rollback.

For missing telemetry, inspect `up{job="kubelet",metrics_path="/metrics/cadvisor"}`
and verify the Talos mapping and kubelet's four root gauges. A stable or
increasing free-space series has no runway estimate. Use
`node:talos_ephemeral_observed` to distinguish that case from a missing node.
Filesystem and inode readings cover exhaustion. Per-device I/O, SMART/ATA
health and eMMC wear require separate hardware evidence under
[issue #909](https://github.com/Stuhlmuller/homelab/issues/909).

## Validate and roll back

Run `nix develop --command python3 -I scripts/ci/talos-filesystem-check.py`
for relabel and Prometheus rule regressions. Add `--chart /path/to/kube-prometheus-stack-85.2.0.tgz`
to verify package SHA-256 and compare the rendered kubelet ServiceMonitor
against the pinned defaults.

After protected deployment, check both Prometheus and Grafana Applications
are Synced and Healthy. Require four mapped series per node in this query,
then confirm the three dashboard panels render their recording rules:

```promql
count by (node, device) ({job="kubelet",metrics_path="/metrics/cadvisor",homelab_talos_volume="EPHEMERAL"})
```

Verify the Alertmanager configuration reloaded after the ExternalSecret
refresh. Check the rules are healthy in Prometheus and that a firing alert reaches
Alertmanager's configured Discord route. A controlled receiver test requires
its own reviewed, temporary rule and a timestamped receipt of the firing and
resolved messages in the destination. Rule fixtures and notification counters
alone leave that delivery check open. Roll back the chart filter, rule resource
and dashboard panels together through a reviewed revert.
