# PVC Metrics Recovery

The September 6, 2026 storage audit found no `kubelet_volume_stats_*` samples
in Prometheus over 24 hours. All four live Kubernetes `v1.34.1` kubelets also
omitted these metrics from `/metrics`, although `/stats/summary` reported
mounted-PVC filesystem statistics. All 48 PVCs were bound and all six
PostgreSQL readiness probes had successful `SELECT 1` checks throughout the
preceding hour. Missing telemetry was not evidence of full disks or failed SQL.

This matches upstream [Kubernetes issue #133847](https://github.com/kubernetes/kubernetes/issues/133847):
an early metrics registration prevents the volume collector from registering.
The [fix](https://github.com/kubernetes/kubernetes/pull/133890) is present in
[the `v1.34.2` collector initialization](https://github.com/kubernetes/kubernetes/blob/v1.34.2/pkg/kubelet/kubelet.go#L1634-L1638).
Choose a currently compatible `1.34.z` patch through the
[declared upgrade workflow](../../talos-control-plane-maintenance.md#talos-and-kubernetes-upgrade-checklist),
with its preflight and backup gates; `1.34.2` identifies verified fixed source,
not the target for a new upgrade.

## Immediate Alert Guard

The existing `homelab-pvc-space-low` rule in
[Grafana values](../../../clusters/homelab/apps/grafana/values.yaml) now sets
`noDataState: Alerting`. Previously an empty query returned `OK`. Its UID,
namespace selector, threshold, and pending duration remain unchanged. A missing
result now signals unavailable coverage; investigate the query before treating
the notification as capacity exhaustion. This guards total absence, not the
loss of one claim while other claims still return samples.

NFS subdirectory PVC statistics describe the shared QNAP filesystem. They do
not measure individual PVC consumption against its requested size. Node-local
filesystem coverage remains the separate work in
[PR #914](https://github.com/Stuhlmuller/homelab/pull/914); it does not restore
the missing PVC collector. Neither this alert change nor a Kubernetes patch
implements the monitoring storage migration or paired n8n recovery design.

## Verification And Rollback

After the reviewed Kubernetes upgrade, verify every node reports the selected
version. Check `/api/v1/nodes/<node>/proxy/metrics` for capacity and available
byte samples, then query both metric families in Prometheus. Match their PVC
labels to currently mounted supported volumes; retained, unmounted claims and
unsupported local volume types must not be counted as healthy coverage.

After GitOps provisions the alert guard, verify its existing UID and
`noDataState` in Grafana, confirm evaluation with real storage samples, and
complete a controlled notification-delivery test. Rendering proves the
provisioned settings, not live evaluation or delivery. Roll back the alert
configuration by reverting this change through GitOps; that restores the
known missing-data blind spot. Kubernetes upgrade recovery follows its own
runbook and backup gates, independently of the alert configuration.

Related: [[architecture/storage-and-state]], [[operations/validation-gates]].
