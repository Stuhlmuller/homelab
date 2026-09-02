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

## Validation

After Argo CD syncs the application:

```sh
argocd app get kiali
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

If this `ClusterIP` path breaks, keep the Service private and repair the
Octelium route. Do not restore direct Tailscale exposure.
