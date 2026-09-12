# Prometheus Storage Profile

Prometheus persists metrics and Alertmanager state on `nfs-default`.
Prometheus also discovers repo-owned ServiceMonitor objects in the `monitoring`
namespace so independent Applications, such as Grafana, can expose metrics
without spoofing the Prometheus Helm release label.
Repo-owned PrometheusRule objects are selected the same way, which lets
non-chart alert rules load without a Helm release label.

## Alert Routing

Alertmanager owns homelab notification fanout. Grafana-managed alerts route to
the `homelab-alertmanager` Grafana contact point, which posts alerts to this
Alertmanager. Alertmanager then delivers notifications to Discord with its
native Discord receiver.

The root route repeats notifications every hour while an alert remains active.
Discord also receives a resolved notification after the alert clears because
its receiver has `send_resolved` enabled. Keep the Grafana notification policy
repeat interval aligned with this route so both stages preserve that cadence.
Alerts are grouped by alert name and namespace so one workload incident sends
one Discord notification instead of one request per pod or container. The
Discord title and message contain only status, alert name, namespace, and alert
counts, keeping grouped notifications below Discord's embed limits.

The `alertmanager-discord-webhook` ExternalSecret reads the existing
`/homelab/grafana/discord-webhook-url` SSM parameter. External Secrets renders
the Discord URL into Alertmanager's runtime config Secret because the
Prometheus Operator schema does not support `webhook_url_file` for Discord.
The secret is not committed.

## Job Failure Recovery

`job-prometheusrules.yaml` replaces the chart's `KubeJobFailed` rule while
keeping its warning severity and 15-minute delay. Only `condition="true"`
counts as a failure: kube-state-metrics also emits false/unknown condition
gauges whose value can be one. Retained failed CronJob runs
stop alerting only when metrics prove their owner succeeded after the failure.
Standalone Jobs and CronJobs without a newer success continue alerting. Do not
delete failed Jobs to clear notifications; their retained status is evidence.
The dedicated rule group evaluates every five minutes to bound history-query
cost. Detection can therefore take up to five minutes before the unchanged
15-minute firing hold; a proven recovery clears on the next group evaluation.

Job creation alone cannot establish that ordering: overlapping runs can fail
after another run succeeds. kube-state-metrics exposes no failure-transition
timestamp, so the rule uses a timestamp from an actual failed-condition sample.
Its 15-day history matches Prometheus retention, sampled every five minutes.
Current Job creation excludes older incarnations with reused names. A unique
controller owner, CronJob creation no later than the Job, and zero active Job
Pods are also required before suppression. Joins include namespace, and
duplicate scrape targets are deduplicated.
The failure signal also uses only namespace and Job name, so overlapping
scrape targets cannot duplicate alerts or reset a pending firing hold when
kube-state-metrics is replaced.

Missing ownership, activity, creation, success, or historical evidence keeps
the failure eligible for alerting. Coarse sampling, lost history, or a success
older than retention may require another successful run to establish recovery.
Suspending a CronJob does not suppress failures; retirement needs a separate,
explicitly scoped decision. Backup-staleness alerts remain independent.

Run `nix develop --command python3 scripts/ci/job-alert-recovery-check.py` to
exercise the actual rules with synthetic failure/success ordering, overlapping
runs, later failures, reused names, namespace boundaries, missing metrics, and
duplicate scrapes. The full static gate runs the same promtool fixtures.
The metric contracts are documented upstream for
[Jobs](https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/job-metrics.md)
and [CronJobs](https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/cronjob-metrics.md).

After Argo CD reconciles, verify `job-failure-recovery` exists and Prometheus
reports one healthy `KubeJobFailed` rule in the `homelab.jobs` group. Check that
the five-minute group remains healthy and its evaluation duration stays well
below its interval. Verify recovered historical failures disappear while later
failures remain. Roll back
by reverting both the custom rule registration and
`defaultRules.disabled.KubeJobFailed`; this restores the chart rule without
removing Job evidence.

## Argo CD Metrics

`argocd-servicemonitors.yaml` owns the ServiceMonitor resources that scrape the
Argo CD application controller, repo server, and API server metrics services in
the `argocd` namespace. The matching services are enabled by the Argo CD
bootstrap stack at `IaC/bootstrap/argocd`; the ServiceMonitors live here so
Prometheus Operator CRDs are installed before this scrape wiring is applied.

`argocd-prometheusrules.yaml` owns Prometheus-native Argo CD alert rules for
missing `argocd_app_info`, unhealthy applications, applications stuck
Progressing, and applications stuck OutOfSync. These intentionally duplicate
the high-value Grafana-managed Argo CD alerts so Alertmanager still receives
Argo CD application failures directly when Grafana provisioning, rule
evaluation, or Grafana's Alertmanager contact point is unhealthy.

`deluge-servicemonitor.yaml` scrapes the Deluge metrics sidecar in the `media`
namespace. That sidecar exposes `deluge_daemon_rpc_healthy`, which checks
whether `deluge-console status` can reach `deluged`. This catches Deluge daemon
state-restore failures that do not make the Kubernetes Pod or Argo CD
Application unhealthy.

- Backup: covered by the NFS backup gate in `docs/storage-nfs.md`.
- Restore: restore Prometheus and Alertmanager PVCs before relying on retained
  metrics.
- Rollback: preserve PVCs unless the operator accepts metrics loss.

## Talos Component Metrics

The kube-prometheus-stack defaults for kube-controller-manager, kube-scheduler,
and kube-proxy are disabled for this cluster. Read-only inspection on
2026-05-24 showed those Talos-managed components were healthy, but their
metrics listeners were bound to loopback or otherwise unavailable on the node
IPs that kube-prometheus-stack targets. Leaving the defaults enabled created
permanent `TargetDown`, `KubeProxyInstanceUnreachable`,
`KubeSchedulerInstanceUnreachable`, and
`KubeControllerManagerInstanceUnreachable` alerts without a repo-owned Talos
metrics exposure path.

Before re-enabling those chart sections or default rule groups, add the matching
Talos machine-config patches in `.talos/`, validate them with
`talosctl validate --mode metal --strict`, apply them through the documented
Talos workflow, and confirm the relevant Prometheus targets are `up`.

The default `Watchdog` alert is also disabled until this homelab has an
external dead-man's-switch receiver. Without that receiver, `Watchdog` is
expected to remain permanently firing in the UI but does not prove anything
actionable.

## Ingress

Prometheus is intentionally not exposed through the tailnet ingress gateway.
Grafana remains the reviewed operator UI for metrics and reads Prometheus over
the in-cluster service URL configured in `clusters/homelab/apps/grafana`.

Do not add a Prometheus `VirtualService` until the access path has a reviewed
authentication story, an owner, and a rollback note. If temporary direct access
is required for an incident, prefer a short-lived operator port-forward after
read-only diagnosis and record the reason in the PR or incident notes.

## Validation

Render Prometheus-owned resources:

```sh
kubectl kustomize clusters/homelab/apps/prometheus
```

After Argo CD and Prometheus sync, verify the Argo CD scrape wiring:

```sh
kubectl -n argocd get svc argocd-application-controller-metrics argocd-repo-server-metrics argocd-server-metrics
kubectl -n monitoring get servicemonitor argocd-application-controller argocd-repo-server argocd-server
kubectl -n monitoring get prometheusrule argocd-application-health
kubectl -n monitoring get externalsecret alertmanager-discord-webhook alertmanager-openclaw-alert-hook
kubectl -n monitoring get secret alertmanager-discord-webhook alertmanager-openclaw-alert-hook
```
