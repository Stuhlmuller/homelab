# Octelium Public Control Plane

This app runs the outbound Cloudflare Tunnel connector that makes only the
Octelium Cluster control-plane hostnames reachable from outside the tailnet:

- `stinkyboi.com`
- `octelium.stinkyboi.com`
- `portal.stinkyboi.com`
- `octelium-api.stinkyboi.com`

Application hostnames such as `grafana.stinkyboi.com` and
`argocd.stinkyboi.com` still resolve to Octelium private Service addresses and
are reached through an authenticated Octelium client session.

## Secret Contract

`octelium-public-cloudflared-credentials` reads
`/homelab/octelium/cloudflare-tunnel-credentials-json` and
`/homelab/octelium/cloudflare-tunnel-id` from AWS SSM. Store the credentials
JSON and UUID created by `cloudflared tunnel create homelab-octelium-public`
at those paths. Do not commit the JSON file, tunnel secret, or Cloudflare API
tokens.

## Routing

`cloudflared` forwards each public hostname to the in-cluster Istio gateway at
`https://istio-ingressgateway.istio-system.svc.cluster.local:443` while setting
the matching origin SNI and Host header. Istio then uses the existing
`octelium-cluster` `VirtualService` to route to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`.

The Cloudflare DNS records for the public hostnames must be exact proxied
CNAMEs to the named tunnel target, `<tunnel-uuid>.cfargotunnel.com`. Reconcile
them with `scripts/octelium-public-dns.sh` after the tunnel UUID is stored in
SSM. Public resolvers should return Cloudflare anycast A/AAAA records, not the
old tailnet `100.64.0.0/10` address.

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
