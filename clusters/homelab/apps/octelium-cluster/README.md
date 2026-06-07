# Octelium Cluster Front Door

This app owns the repo-side Octelium Cluster ingress route. `octops init`
creates and manages the Octelium control-plane workloads in the `octelium`
namespace, while this Argo CD Application keeps the homelab's Istio bootstrap
gateway routing the Octelium public hostnames to the Octelium data-plane
ingress service. It deliberately does not create or manage the `octelium`
namespace because Octelium genesis deletes and recreates that namespace during
`octops init`. Automated pruning is disabled for this small front-door app so
the previous repo-owned `Namespace/octelium` object is not pruned during the
handoff to `octops` ownership.

The bootstrap script runs `octops init` with Octelium ingress front-proxy mode,
so Istio terminates TLS and proxies HTTP to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`. The paired
`DestinationRule` forces HTTP/2 upstream traffic to that Octelium dataplane
Service so CLI gRPC responses keep their trailers.

Client VPN traffic uses Octelium Gateway hostnames generated from the cluster
domain, such as `_gw-*.stinkyboi.com`, not the Istio front-proxy route. After
`octops` creates or updates Gateway status, run
`scripts/octelium-gateway-dns.sh --dry-run` and then
`scripts/octelium-gateway-dns.sh` so those exact hostnames resolve to the
advertised gateway IPv6 addresses instead of falling through to the tailnet
wildcard DNS record.

Application hostnames stay on the existing `*.stinkyboi.com` names. After the
Octelium service catalog is applied and Service status reports private
addresses, run `scripts/octelium-app-dns.sh --dry-run` and then
`scripts/octelium-app-dns.sh` so exact app names such as
`grafana.stinkyboi.com` resolve to Octelium `fdee:b76e:*` IPv6 service IPs.

## Validation

```sh
kubectl -n istio-system get destinationrule octelium-cluster-dataplane
kubectl -n octelium get svc octelium-ingress-dataplane
kubectl -n istio-system get virtualservice octelium-cluster
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-app-dns.sh --dry-run
curl -I https://octelium.stinkyboi.com
curl -I https://portal.stinkyboi.com
curl -I https://octelium-api.stinkyboi.com
```
