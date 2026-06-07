# Octelium Public Control Plane

This app runs the outbound Cloudflare Tunnel connector that makes only the
Octelium Cluster control-plane hostnames reachable from outside the tailnet:

- `octelium.stinkyboi.com`
- `portal.octelium.stinkyboi.com`
- `octelium-api.octelium.stinkyboi.com`

Application hostnames such as `grafana.stinkyboi.com` and
`argocd.stinkyboi.com` still resolve to Octelium private Service addresses and
are reached through an authenticated Octelium client session.

## Secret Contract

`octelium-public-cloudflared-credentials` reads
`/homelab/octelium/cloudflare-tunnel-credentials-json` from AWS SSM. Store the
credentials JSON created by `cloudflared tunnel create
homelab-octelium-public` at that path. Do not commit the JSON file, tunnel
secret, or Cloudflare API tokens.

## Routing

`cloudflared` forwards each public hostname to the in-cluster Istio gateway at
`https://istio-ingressgateway.istio-system.svc.cluster.local:443` while setting
the matching origin SNI and Host header. Istio then uses the existing
`octelium-cluster` `VirtualService` to route to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`.

The Cloudflare DNS records for the three public hostnames must be CNAMEs to the
named tunnel target, `<tunnel-uuid>.cfargotunnel.com`.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/octelium-public
kubectl -n octelium-public get externalsecret,secret,deploy,pod
kubectl -n octelium-public logs deploy/cloudflared
dig +short octelium.stinkyboi.com CNAME
curl -fsS -o /dev/null -w '%{http_code}\n' https://octelium.stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://portal.octelium.stinkyboi.com/
```
