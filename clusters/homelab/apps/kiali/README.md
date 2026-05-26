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
https://kiali.stinkyboi.com
```

The route uses the shared `istio-system/tailnet-gateway` and is annotated with
`homelab.rst.io/public-funnel: "false"`. Do not add a public Funnel route for
Kiali.

Kiali uses `auth.strategy: anonymous` and `deployment.view_only_mode: true`.
This keeps the UI immediately usable from the tailnet without granting write
operations through Kiali. If this becomes a broader operator surface, replace
anonymous access with OIDC-backed authentication in a separate change.

## Dependencies

Kiali depends on:

- Istio for mesh resources and status.
- Tailscale and the shared tailnet gateway for private HTTPS access.
- Prometheus for graph and health metrics.
- Grafana for dashboard links.

The monitoring AuthorizationPolicies allow the Kiali service account to query
Prometheus and Grafana. Kiali has no persistent storage requirement.

## Validation

After Argo CD syncs the application:

```sh
argocd app get kiali
kubectl -n monitoring get kiali kiali
kubectl -n monitoring get deploy,svc kiali
curl -I https://kiali.stinkyboi.com
```

Expected result: the Argo CD Application is `Synced` and `Healthy`, the Kiali
custom resource reports a successful reconciliation, the Deployment and Service
exist in `monitoring`, and the tailnet HTTPS route returns a Kiali response.

Rollback by reverting the `kiali` Application registration and this desired
state path, then syncing Argo CD. Let the Kiali CR delete cleanly before
removing the operator chart so the operator can remove its managed resources.
