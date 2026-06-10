# Octelium Public Control Plane

This app runs the outbound Cloudflare Tunnel connector that makes the Octelium
Cluster control-plane hostnames and clientless app hostnames reachable from
outside the tailnet:

- `stinkyboi.com`
- `octelium.stinkyboi.com`
- `portal.stinkyboi.com`
- `octelium-api.stinkyboi.com`
- `argocd.stinkyboi.com`, `console.stinkyboi.com`,
  `grafana.stinkyboi.com`, and the other app FQDNs declared in
  `docs/examples/octelium/homelab-services.yaml`

## Secret Contract

`octelium-public-cloudflared-credentials` reads
`/homelab/octelium/cloudflare-tunnel-credentials-json` and
`/homelab/octelium/cloudflare-tunnel-id` from AWS SSM. Store the credentials
JSON and UUID created by `cloudflared tunnel create homelab-octelium-public`
at those paths. Do not commit the JSON file, tunnel secret, or Cloudflare API
tokens.

## Routing

`cloudflared` forwards the Octelium control-plane hostnames to the in-cluster
Istio gateway at `https://istio-ingressgateway.istio-system.svc.cluster.local:443`
while setting the matching origin SNI and Host header. Istio then uses the
existing `octelium-cluster` `VirtualService` to route to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`.

App hostnames forward directly to
`http://octelium-ingress-dataplane.octelium.svc.cluster.local:8080` with their
original Host headers. Octelium uses that public FQDN to select the matching
`WEB` Service, enforce login, and then proxy to the existing Istio app route.
The Enterprise console follows the same browser path: `console.stinkyboi.com`
enters the Octelium clientless dataplane through the public `console.homelab`
WEB app-hostname Service, then Istio routes the backend request to
`svc-console-octelium`. Keep this on `console.stinkyboi.com`; the package-owned
system console's canonical `console.octelium.stinkyboi.com` name is a nested
hostname and is not part of the public certificate/DNS shape.

The Cloudflare DNS records for the public hostnames and app hostnames must be
exact proxied CNAMEs to the named tunnel target,
`<tunnel-uuid>.cfargotunnel.com`. Reconcile them with
`scripts/octelium-public-dns.sh` after the tunnel UUID is stored in SSM. Public
resolvers should return Cloudflare anycast A/AAAA records, not private Octelium
or old tailnet addresses.

Cloudflare edge TLS and Istio origin TLS use the apex plus first-level
`*.stinkyboi.com` certificate shape. The cluster domain is `stinkyboi.com` so
the Octelium client calls `octelium-api.stinkyboi.com`; the
`octelium.stinkyboi.com` hostname is only an alias.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/octelium-public
kubectl -n octelium-public get externalsecret,secret,deploy,pod
kubectl -n octelium-public logs deploy/cloudflared
scripts/octelium-public-dns.sh --dry-run
dig +short octelium.stinkyboi.com
curl -fsS -o /dev/null -w '%{http_code}\n' https://stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://octelium.stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://portal.stinkyboi.com/
```
