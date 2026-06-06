# Octelium Cluster Front Door

This app owns the repo-side Octelium Cluster ingress route. `octops init`
creates and manages the Octelium control-plane workloads in the `octelium`
namespace, while this Argo CD Application keeps the homelab's Istio bootstrap
gateway routing the nested Octelium hostnames to the Octelium data-plane
ingress service.

The bootstrap script runs `octops init` with `OCTELIUM_FRONT_PROXY_MODE=true`,
so Istio terminates TLS and proxies HTTP to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`.

## Validation

```sh
kubectl -n octelium get svc octelium-ingress-dataplane
kubectl -n octelium get virtualservice octelium-cluster
curl -I https://octelium.stinkyboi.com
curl -I https://portal.octelium.stinkyboi.com
curl -I https://octelium-api.octelium.stinkyboi.com
```
