# Tailnet Ingress

Tags: #runbooks #networking #tailscale #istio

Source: `docs/networking-tailnet-ingress.md`

## Model

Octelium is the primary access plane for app UIs, VPN sessions, CI Kubernetes
API reachability, and external callbacks. App hostnames stay on
`*.stinkyboi.com`, but exact DNS records resolve as proxied Cloudflare Tunnel
CNAMEs to the repo-owned `octelium-public` connector instead of Octelium
private service addresses or the old Tailscale wildcard route. Tailscale Funnel
is no longer an approved external-service backbone in steady state.

The Octelium control-plane names, app hostnames, and reviewed callback names
all use proxied Cloudflare CNAMEs to the `homelab-octelium-public` Cloudflare
Tunnel target. Public DNS returns Cloudflare anycast addresses, while the
Cloudflare zone metadata keeps the `<tunnel-uuid>.cfargotunnel.com` target.
The in-cluster `octelium-public` app runs `cloudflared`; app UI hostnames go to
the Octelium ingress dataplane for clientless login, while control-plane,
Enterprise console, and unauthenticated callback hostnames go to the Istio
gateway with explicit `VirtualService` routing.

The Octelium service catalog in `docs/examples/octelium/homelab-services.yaml`
keeps the existing app URLs by storing each `*.stinkyboi.com` hostname as a
service attribute and forwarding HTTPS to the in-cluster Istio gateway. The
internal HTTPS hop avoids the gateway's HTTP-to-HTTPS redirect loop for
authenticated clientless browser requests. The per-app Istio `VirtualService`
objects are private backend routes for that Octelium path, not public Funnel
routes.

Octelium is documented under [[octelium]]. It is the primary app, callback,
VPN, and CI access backbone. Tailscale remains only for the secondary exit-node
and LAN route use cases documented below.

## Current Route Rules

- Argo CD, Grafana, Kiali, Deluge, Dispatcharr, Prowlarr, Radarr, Sonarr,
  LiteLLM, OpenClaw, n8n editor/UI, Policy Bot UI and normal routes, and
  OctoBot UI use Octelium-backed `*.stinkyboi.com` app hostnames.
- n8n webhooks use the reviewed Octelium-public callback host
  `https://n8n-webhook.stinkyboi.com` for `/webhook`, `/webhook-test`, and
  `/webhook-waiting` only. External callers using the retired Funnel hostname
  must be updated after rollout.
- Policy Bot GitHub webhook uses the reviewed Octelium-public callback host
  `https://policy-bot-hook.stinkyboi.com/api/github/hook`; update the GitHub
  App webhook URL after rollout.
- Prometheus is intentionally not exposed; Grafana is the metrics UI and Kiali
  is the read-only mesh UI.
- OctoBot uses `https://octobot.stinkyboi.com` through Octelium. Its exchange
  credentials and strategy state live on PVC-backed runtime
  configuration, not in public repository files.
- Octelium serves app UI Services from
  `docs/examples/octelium/homelab-services.yaml`; public webhook callbacks use
  path-limited Istio routes reached through `octelium-public`.
- Octelium control-plane/API/portal access is public through Cloudflare Tunnel
  so users can log in and start the VPN without already being on Tailscale.

## TLS And Certificates

Istio terminates HTTPS with `stinkyboi-com-tls` in `istio-system`.
cert-manager requests the apex plus first-level wildcard certificate through
`letsencrypt-cloudflare`, backed by the `cloudflare-api-token` Secret from
External Secrets. That certificate covers the Octelium domain
`stinkyboi.com`, API, portal, alias, and private app backend hostnames.

## Homelab Exit Node

The `tailscale` Application installs the Tailscale operator and the
`homelab-exit-node` Connector. This is a secondary LAN/egress utility, not the
primary app, callback, VPN, or GitHub Actions backbone. The connector
advertises itself as an exit node with tag `tag:k8s` and advertises
`10.1.0.0/24` so tailnet clients can reach the homelab LAN when Octelium is
unavailable or a local-LAN workflow has not moved. GitHub Actions uses
Octelium Service `kubernetes-api.ci`.

Validation:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=homelab-exit-node
```

## Callback Template

Every future public callback route needs owner, path, purpose, source system,
authentication or signature check, public callback hostname, backbone, rollback
command, and data exposure. Rendered resources must pass the Conftest rule that
rejects Tailscale Funnel and requires `homelab.rst.io/access-plane: octelium`
for public routes.

## Related Notes

- [[../architecture/secrets-and-identity]]
- [[../workloads/application-notes]]
- [[validation]]
