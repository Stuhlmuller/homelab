# Prometheus Storage Profile

Prometheus persists metrics and Alertmanager state on `nfs-default`.
Prometheus also discovers repo-owned ServiceMonitor objects in the `monitoring`
namespace so independent Applications, such as Grafana, can expose metrics
without spoofing the Prometheus Helm release label.

## Alert Routing

Alertmanager owns homelab notification fanout. Grafana-managed alerts route to
the `homelab-alertmanager` Grafana contact point, which posts alerts to this
Alertmanager. Alertmanager then delivers notifications to Discord with the
native Discord receiver and to OpenClaw's authenticated `/hooks/agent` endpoint
with a bearer-token webhook receiver.

The `alertmanager-discord-webhook` and `alertmanager-openclaw-alert-hook`
ExternalSecrets read the existing `/homelab/grafana/discord-webhook-url` and
`/homelab/grafana/openclaw-alert-hook-token` SSM parameters. The Alertmanager
pods mount those target Secrets under `/etc/alertmanager/secrets/` so the
receiver config uses file-backed credentials instead of committing secret
values or depending on Grafana-owned runtime state.

## Argo CD Metrics

`argocd-servicemonitors.yaml` owns the ServiceMonitor resources that scrape the
Argo CD application controller, repo server, and API server metrics services in
the `argocd` namespace. The matching services are enabled by the Argo CD
bootstrap stack at `IaC/bootstrap/argocd`; the ServiceMonitors live here so
Prometheus Operator CRDs are installed before this scrape wiring is applied.

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
kubectl -n monitoring get externalsecret alertmanager-discord-webhook alertmanager-openclaw-alert-hook
kubectl -n monitoring get secret alertmanager-discord-webhook alertmanager-openclaw-alert-hook
```
