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

`octelium-api.stinkyboi.com` serves the browser API;
`octelium-transport.stinkyboi.com` carries native clients over TCP.

## Secret Contract

`octelium-public-cloudflared-credentials` reads
`/homelab/octelium/cloudflare-tunnel-credentials-json` and
`/homelab/octelium/cloudflare-tunnel-id` from AWS SSM. Store the credentials
JSON and UUID created by `cloudflared tunnel create homelab-octelium-public`
at those paths. Do not commit the JSON file, tunnel secret, or Cloudflare API
tokens.

## Routing

`cloudflared` forwards the browser-facing Octelium control-plane hostnames to
the in-cluster Istio gateway at
`https://istio-ingressgateway.istio-system.svc.cluster.local:443` while setting
the matching origin SNI and Host header. Istio then uses the existing
`octelium-cluster` `VirtualService` to route to
`octelium-ingress-dataplane.octelium.svc.cluster.local:8080`.
The API uses two outbound Cloudflare Tunnel routes. Browser gRPC-Web uses
`octelium-api.stinkyboi.com` over HTTPS. Native Octelium and Cordium clients
use `octelium-transport.stinkyboi.com`, a TCP-over-WebSocket carrier to the
existing API-only Istio TLS gateway. Both DNS records are proxied CNAMEs to
`<tunnel-uuid>.cfargotunnel.com`. No router forward or WAN address is required.
The inner connection retains `octelium-api.stinkyboi.com` for certificate
verification, HTTP/2, and Octelium authentication.

Cloudflare does not support native gRPC on public HTTP Tunnel routes. Its
[supported TCP carrier](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/)
transports the TLS stream instead. Cloudflare warns that long-lived carrier
connections can disconnect; require real Cordium execution, terminal streaming,
and reconnect tests before treating this as a proven execution transport.
An account policy requiring Cloudflare Access may add a separate login gate;
the carrier does not grant Octelium authorization.

App hostnames forward directly to
`http://octelium-ingress-dataplane.octelium.svc.cluster.local:8080` with their
original Host headers. Octelium uses that public FQDN to select the matching
`WEB` Service and then proxy to the existing Istio app route. The Services
enforce login except for AFFiNE's reviewed anonymous transport, which lets its
native client connect. NOFX requires Octelium login before its application login.
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

After Argo CD loads the new `octelium-public` pod revision, run the protected
workflow to remove the retired WAN origin rules and reconcile Tunnel DNS:

```sh
gh workflow run octelium-public-tunnel.yml --ref main -f expected_sha='<reviewed-main-sha>'
nix develop --command python3 scripts/octelium-tunnel-check.py
```

The workflow uses the existing production AWS role to read the DNS token and
Tunnel UUID from SSM, and `CLOUDFLARE_ZONE_SETTINGS_TOKEN` to remove the old
hostname-specific origin/TLS rules. The latter needs zone read, Origin Rules
edit, and Config Settings write. API responses remain in a temporary private
log. Retry after correcting declared inputs if any stage fails; partial DNS
changes are possible and the workflow is idempotent.

The old UPnP CronJob is suspended and its Grafana lease alert paused. It no
longer renews router mappings; any prior leased mapping expires naturally.
The dedicated gateway and cluster split DNS remain available for in-cluster
clients. The legacy origin-port apply workflow now rejects use.

For rollback, revert the Tunnel configuration and pod revision through a
reviewed PR. Do not restore WAN DNS or port forwarding without a separately
reviewed transport change. Preserve private cluster access during rollout.

Native clients need a local TCP carrier and a resolver mapping scoped to
their execution environment. The pinned Octelium client calls the canonical
API hostname on port 443:

```sh
cloudflared access tcp --hostname octelium-transport.stinkyboi.com --url 127.0.0.1:443
```

In a dedicated client container or Pod, map `octelium-api.stinkyboi.com` to
`127.0.0.1` (for example, a declared Pod `hostAliases` entry) and run the
carrier in that same network namespace. Binding port 443 may require the
container's low-port capability. Keep the transport hostname publicly resolved;
do not map it to loopback. Do not add a workstation-wide hosts entry that
would redirect the browser's gRPC-Web traffic. The standalone transport probe
uses a temporary high port and curl `--connect-to`, so it needs neither root
nor a hosts-file change. CI and OpenClaw client integration remains a separate
rollout gate; the carrier probe alone does not prove authenticated execution.

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
python3 scripts/octelium-tunnel-check.py
dig +short octelium.stinkyboi.com
curl -fsS -o /dev/null -w '%{http_code}\n' https://stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://octelium.stinkyboi.com/
curl -fsS -o /dev/null -w '%{http_code}\n' https://portal.stinkyboi.com/
```
