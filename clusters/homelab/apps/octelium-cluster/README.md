# Octelium Cluster Front Door

This app owns the repo-side Octelium Cluster ingress route. `octops init`
creates and manages the Octelium control-plane workloads in the `octelium`
namespace, while this Argo CD Application keeps the homelab's Istio bootstrap
gateway routing the Octelium public hostnames to the Octelium data-plane
ingress service, plus `console.stinkyboi.com` directly to the Enterprise
console Service. It deliberately does not create or manage the `octelium`
namespace because Octelium genesis deletes and recreates that namespace during
`octops init`. Automated pruning is disabled for this small front-door app so
the previous repo-owned `Namespace/octelium` object is not pruned during the
handoff to `octops` ownership.

The bootstrap script runs `octops init` with Octelium ingress front-proxy mode,
so Istio terminates TLS and proxies HTTP to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`. The paired
`DestinationRule` forces HTTP/2 upstream traffic to that Octelium dataplane
Service so CLI gRPC responses keep their trailers.
The Enterprise console is the exception: `console.stinkyboi.com` routes to the
package-owned `svc-console-octelium` Service so the public URL stays first-level
and does not require the nested `console.octelium.stinkyboi.com` hostname.

The package still generates browser login return URLs with that nested name.
`console-redirect.yaml` adds a scoped Lua response filter to the existing
`istio: ingressgateway` workload. Only requests for `console.stinkyboi.com`
with HTTP 303 and `x-octelium-unauthorized: true` qualify. The filter replaces
only the exact canonical login-return prefix, preserving the encoded path and
query. Cookies, authentication, status codes, response bodies, and unrelated
redirects are untouched. Core 0.35.0 accepts the friendly hostname as a valid
login return; neither Enterprise 0.22.0 nor 0.29.0 exposes a console-alias
setting. See the source-backed
[capability research](../../../../docs/knowledge-base/operations/octelium-capability-research-2026-09-05.md).

The static gate runs the actual Lua against root, deep-link, query, wrong-host,
wrong-status, missing-marker, and lookalike-target cases. After GitOps rollout,
require a browser login return to the friendly hostname, then separately verify
console queries through `octelium-api.stinkyboi.com`. This filter does not repair
the public API transport. Because this app disables automated pruning, roll
back by committing an empty `spec.configPatches` list and adjusting its
regression gate, rather than merely removing the file from Kustomization.

Client VPN traffic uses Octelium Gateway hostnames generated from the cluster
domain, such as `_gw-*.stinkyboi.com`, not the Istio front-proxy route. After
`octops` creates or updates Gateway status, run
`scripts/octelium-gateway-dns.sh --dry-run` and then
`scripts/octelium-gateway-dns.sh` so those exact hostnames resolve to the
advertised gateway IPv6 addresses instead of falling through to the tailnet
wildcard DNS record.

Application hostnames stay on the existing `*.stinkyboi.com` names. After the
Octelium service catalog is applied, run `scripts/octelium-public-dns.sh
--dry-run` and then `scripts/octelium-public-dns.sh` so exact app names such as
`grafana.stinkyboi.com` and callback names such as
`n8n-webhook.stinkyboi.com` resolve as proxied Cloudflare Tunnel CNAMEs to the
repo-owned `octelium-public` connector.

## Validation

```sh
kubectl -n istio-system get destinationrule octelium-cluster-dataplane
kubectl -n octelium get svc octelium-ingress-dataplane
kubectl -n istio-system get virtualservice octelium-cluster
scripts/octelium-gateway-dns.sh --dry-run
scripts/octelium-public-dns.sh --dry-run
curl -I https://octelium.stinkyboi.com
curl -I https://portal.stinkyboi.com
curl -I https://octelium-api.stinkyboi.com
```
