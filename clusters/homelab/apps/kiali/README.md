# Kiali

Kiali is the read-only Istio mesh UI for this homelab. It is installed through
the official `kiali-operator` Helm chart and managed by the `kiali` Argo CD
Application registered from `IaC/live/argocd-apps/kiali`.

The operator runs from the chart release namespace, while the Kiali custom
resource deploys the Kiali server into `monitoring`. The Kiali CR sets
`istio_namespace: istio-system` so Kiali watches the existing Istio control
plane while using the monitoring namespace's existing observability boundary.

## Access

Kiali is exposed at:

```text
kiali.homelab
```

The Octelium service is the target human access path. The existing
`https://kiali.stinkyboi.com` hostname resolves to the Octelium service address
and reaches Kiali through the published `kiali.homelab` Service. Do not add a
public Funnel route for Kiali. The primary Istio gateway is `ClusterIP` only;
Kiali has no direct Tailscale LoadBalancer path around Octelium authentication.

Kiali uses `auth.strategy: anonymous` and `deployment.view_only_mode: true`,
with an Istio `AuthorizationPolicy` that allows Octelium service-proxy traffic
through the Istio gateway and Prometheus to reach the Kiali workload. This keeps
the UI immediately usable without granting write operations through Kiali. If
this becomes a broader operator surface, replace anonymous access with
OIDC-backed authentication in a separate change.

## Dependencies

Kiali depends on:

- Istio for mesh resources and status.
- Octelium for app access.
- Prometheus for graph and health metrics.
- Grafana for dashboard links.

The monitoring AuthorizationPolicies allow the Kiali service account to query
Prometheus and Grafana, and allow Prometheus plus the Octelium service-proxy path
to reach Kiali. Kiali has no persistent storage requirement.

## NetworkPolicy ownership

The pinned Kiali operator creates `monitoring/kiali`, an ingress-only
NetworkPolicy that selects Kiali and admits TCP 20001 and 9090 from any source.
Its supported `deployment.network_policy.enabled` setting can only enable or
disable that policy. The [pinned operator delete task](https://github.com/kiali/kiali-operator/blob/v2.26.0/roles/default/kiali-deploy/tasks/kubernetes/k8s-main.yml#L58-L67)
targets only `monitoring/kiali` when disabled.

This application therefore applies `kiali-server-ingress` at Argo CD sync wave
0, before the Kiali custom resource at wave 1 disables the operator policy.
The repository policy has the same complete spec as the observed operator
policy, including its broad source set. The distinct name prevents the
operator's deletion from removing the replacement. This is an ownership
handoff, not an ingress tightening or proof of network enforcement: Flannel
does not enforce NetworkPolicy, and narrower sources still require the
runtime-isolation canary and real Kiali client-traffic evidence.

Before sync, render `clusters/homelab/apps/kiali` and compare the replacement
policy spec to the read-only `monitoring/kiali` spec. After sync, verify that
`kiali-server-ingress` exists, `kiali` is absent, and Kiali remains reachable
through Octelium and scrapeable by Prometheus. If this handoff must be rolled
back after enforcement is active, first re-enable the operator policy while
retaining the repository policy and sync Kiali; remove the repository policy
in a second GitOps change after the operator policy exists. This preserves an
ingress allow rule throughout the rollback.

## Configuration and connections

Use **Select all** in the namespace selector. **Istio Config** lists declared
resources and validation findings; **Traffic Graph** shows observed connections.
Choose a 10-minute window and enable idle edges when inspecting quiet workloads.
Ambient ztunnel traffic is TCP/L4; HTTP request details require a waypoint or
sidecar. Workloads outside Istio are not a complete network inventory in Kiali.

Prometheus owns `istio-podmonitors.yaml`, which scrapes ztunnel, Envoy (gateways,
waypoints and sidecars), and Istiod. The monitors carry `release: prometheus`
to match the Prometheus PodMonitor selector. Metrics retain the existing 15-day
retention and use the existing Prometheus volume; monitor storage growth after
rollout because mesh telemetry adds series.

Kiali 2.26.0 permanently substitutes a no-op metrics client when its startup
Prometheus health check fails. The readiness init container waits for Prometheus
through Kiali's own network identity before starting the server. This requires
the operator's additional-container and security-context override flags; the
reviewed container retains a read-only filesystem, no capabilities, and an
explicit non-root UID. No new cluster permissions or secret access are added.
An unavailable Prometheus keeps new Kiali pods in initialization rather than
silently serving a metrics-disabled UI. The init container invokes `curl`
directly, retries 60 times with a five-second delay, then exits nonzero so
Kubernetes restarts it. Inspect `wait-for-prometheus` logs if initialization
stalls. A failure between the readiness check and server startup is still
possible; the live check below detects that case.

The Kiali CR pins the server image by digest. The operator expects a bare hash
in `deployment.image_version` and `sha256` in `deployment.image_digest`; it
builds the image reference and uses the version value in Kubernetes labels.
Including `@sha256:` in `image_version` makes the ServiceAccount label invalid
and stops reconciliation before a server Deployment exists. The static gate
checks the CR fields against the existing Harbor mirror catalog entry.

## Validation

After Argo CD syncs the application:

```sh
argocd app get kiali
python3 scripts/kiali-check.py
kubectl -n monitoring get kiali kiali
kubectl -n monitoring get deploy,svc kiali
kubectl -n istio-system get service istio-ingressgateway \
  -o jsonpath='{.spec.type}{" "}{.spec.loadBalancerClass}{"\n"}'
kubectl -n tailscale get statefulset,pod \
  -l tailscale.com/parent-resource=istio-ingressgateway
curl -I https://kiali.stinkyboi.com
```

Expected result: the Argo CD Application is `Synced` and `Healthy`, the Kiali
custom resource reports a successful reconciliation, the Deployment and Service
exist in `monitoring`, the primary gateway reports `ClusterIP` with no load
balancer class, no Tailscale proxy remains for that Service, and the
`kiali.stinkyboi.com` hostname responds through Octelium.

If this `ClusterIP` path breaks Octelium routing, revert the Istio gateway
Service change and sync Istio. Do not restore direct Tailscale exposure until
that path has its own authentication policy.

For telemetry rollback, revert the Kiali values and Prometheus monitor changes
in git and let Argo CD reconcile both apps. Historical metrics remain until
normal retention expires. A green Argo CD status alone does not prove traffic
visibility: `scripts/kiali-check.py` requires Kiali metrics enabled and graph
edges from recent real mesh traffic. The direct Kubernetes API server proxy
to Prometheus currently resets, while Kiali's allowed in-mesh query works.
