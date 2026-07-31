# Octelium Public Control Plane

This app runs the outbound Cloudflare Tunnel connector that makes the Octelium
browser control-plane and public app hostnames reachable from outside the
tailnet:

- `stinkyboi.com`
- `octelium.stinkyboi.com`
- `portal.stinkyboi.com`
- `argocd.stinkyboi.com`, `console.stinkyboi.com`,
  `grafana.stinkyboi.com`, and the other app FQDNs declared in
  `docs/examples/octelium/homelab-services.yaml`
- `n8n-webhook.stinkyboi.com` and `policy-bot-hook.stinkyboi.com` for
  reviewed external callbacks that cannot complete an Octelium browser login
- `kubernetes-api-ci.stinkyboi.com` for the policy-bound clientless CI
  Kubernetes Service

`octelium-api.stinkyboi.com` uses the separate direct gRPC origin documented
below.

## Secret Contract

`octelium-public-cloudflared-credentials` reads
`/homelab/octelium/cloudflare-tunnel-credentials-json` and
`/homelab/octelium/cloudflare-tunnel-id` from AWS SSM. Store the credentials
JSON and UUID created by `cloudflared tunnel create homelab-octelium-public`
at those paths. Do not commit the JSON file, tunnel secret, or Cloudflare API
tokens.

## Routing

`cloudflared` forwards the browser-facing Octelium control-plane hostnames to the in-cluster
Istio gateway at `https://istio-ingressgateway.istio-system.svc.cluster.local:443`
while setting the matching origin SNI and Host header. Istio then uses the
existing `octelium-cluster` `VirtualService` to route to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`.
The `octelium-api.stinkyboi.com` CLI hostname does not use this public-hostname
tunnel because Cloudflare does not support gRPC streams on that route type.
It uses Cloudflare's normal proxied gRPC path to public TCP/443, which the
`octelium-api-upnp` CronJob maps with UPnP to the dedicated
`octelium-api-ingressgateway` at `10.1.0.200:30443`.
`scripts/octelium-public-dns.sh` verifies that mapping and reconciles DNS. That gateway's TLS
listener accepts only the API hostname, so app hostnames cannot bypass their
Tunnel and Octelium clientless path through the WAN mapping. The connector
remains pinned to `2026.7.3` for browser, app, and callback routes.

App hostnames forward directly to
`http://octelium-ingress-dataplane.octelium.svc.cluster.local:8080` with their
original Host headers. Octelium uses that public FQDN to select the matching
`WEB` Service and then proxy to the existing Istio app route. The Services
enforce login except for AFFiNE's reviewed anonymous transport, where AFFiNE
owns authentication so its native client can connect.
`cloudflared` reads this routing table only when the pod starts. Whenever
`configmap.yaml` changes, update the
`homelab.rst.io/cloudflared-config-revision` pod-template annotation in
`deployment.yaml` in the same change so Argo CD performs a rolling restart and
the tunnel replicas load the new hostnames.
The Enterprise console is the exception: `console.stinkyboi.com` forwards
directly to the Istio gateway with its original Host header, and
`octelium-cluster` routes it to `svc-console-octelium`. Keep this on
`console.stinkyboi.com`; the package-owned system console's canonical
`console.octelium.stinkyboi.com` name is a nested hostname and is not part of
the public certificate/DNS shape.

The Cloudflare DNS records for browser, app, and callback hostnames must be
exact proxied CNAMEs to the named tunnel target,
`<tunnel-uuid>.cfargotunnel.com`. The API hostname must be a proxied A record
to the WAN address. After Argo CD syncs the `octelium-api-upnp` CronJob,
reconcile DNS with `scripts/octelium-public-dns.sh` from the homelab LAN.
Public resolvers should return Cloudflare anycast addresses, not private
Octelium or old tailnet addresses.

Cloudflare edge TLS and Istio origin TLS use the apex plus first-level
`*.stinkyboi.com` certificate shape. The cluster domain is `stinkyboi.com` so
the Octelium client calls `octelium-api.stinkyboi.com`; the
`octelium.stinkyboi.com` hostname is only an alias.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/octelium-public
kubectl kustomize clusters/homelab/apps/istio
kubectl -n octelium-public get externalsecret,secret,deploy,pod
kubectl -n octelium-public logs deploy/cloudflared
scripts/octelium-public-dns.sh --dry-run
curl -sS --http2 \
  -H 'content-type: application/grpc' \
  -H 'te: trailers' \
  --data-binary '' \
  -o /dev/null \
  -D - \
  https://octelium-api.stinkyboi.com/octelium.api.main.user.v1.MainService/GetStatus
dig +short octelium.stinkyboi.com
curl -fsS -o /dev/null -w '%{http_code}\n' https://stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://octelium.stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://portal.stinkyboi.com/
```
