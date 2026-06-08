# Tailnet Ingress

Tags: #runbooks #networking #tailscale #istio

Source: `docs/networking-tailnet-ingress.md`

## Model

Octelium is the access plane for human app access. App hostnames stay on
`*.stinkyboi.com`, but exact DNS records resolve them to Octelium private
service addresses instead of the old Tailscale wildcard route. Public Tailscale
Funnel is reserved for reviewed webhook paths that external SaaS systems must
reach.

The Octelium control-plane names are the narrow public exception and do not use
Tailscale Funnel. `stinkyboi.com`, `octelium.stinkyboi.com`,
`portal.stinkyboi.com`, and `octelium-api.stinkyboi.com` are proxied
Cloudflare CNAMEs to the
`homelab-octelium-public` Cloudflare Tunnel target. Public DNS returns
Cloudflare anycast addresses, while the Cloudflare zone metadata keeps the
`<tunnel-uuid>.cfargotunnel.com` target. The in-cluster `octelium-public` app
runs `cloudflared` and forwards those hostnames to the Istio gateway, which
preserves the existing Octelium Cluster `VirtualService`.

The Octelium service catalog in `docs/examples/octelium/homelab-services.yaml`
keeps the existing app URLs by storing each `*.stinkyboi.com` hostname as a
service attribute and forwarding HTTPS to the in-cluster Istio gateway. The
internal HTTPS hop avoids the gateway's HTTP-to-HTTPS redirect loop for
authenticated clientless browser requests. The per-app Istio `VirtualService`
objects are private backend routes for that Octelium path, not public Funnel
routes.

Octelium is documented under [[octelium]]. It replaces app access only; it does
not replace the Tailscale exit node, CI route, or reviewed public webhook
exceptions.

## Current Route Rules

- Argo CD, Grafana, Kiali, Deluge, Prowlarr, Radarr, Sonarr, LiteLLM,
  OpenClaw, n8n editor/UI, Policy Bot UI and normal routes, and OctoBot UI use
  Octelium-backed `*.stinkyboi.com` app hostnames.
- n8n webhooks are a reviewed public Funnel exception:
  `https://n8n-webhook.tail67beb.ts.net` for `/webhook`, `/webhook-test`, and
  `/webhook-waiting` only.
- Policy Bot GitHub webhook is another reviewed public Funnel exception:
  `https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook`.
- Prometheus is intentionally not exposed; Grafana is the metrics UI and Kiali
  is the read-only mesh UI.
- OctoBot uses `https://octobot.stinkyboi.com` through Octelium. Its exchange
  credentials and strategy state live on PVC-backed runtime
  configuration, not in public repository files.
- Octelium serves private app Services from
  `docs/examples/octelium/homelab-services.yaml`; public webhook callbacks stay
  on their reviewed Tailscale Funnel exceptions until separately redesigned.
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
`homelab-exit-node` Connector. The connector advertises itself as an exit node
with tag `tag:k8s` and advertises `10.1.0.0/24` so tailnet clients can reach
the homelab LAN. CI grants stay limited to `10.1.0.199:6443` for Kubernetes API
access.

Validation:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=homelab-exit-node
```

## Funnel Exception Template

Every future public route needs owner, path, purpose, source system,
authentication or signature check, Funnel hostname, rollback command, and data
exposure.

## Related Notes

- [[../architecture/secrets-and-identity]]
- [[../workloads/application-notes]]
- [[validation]]
