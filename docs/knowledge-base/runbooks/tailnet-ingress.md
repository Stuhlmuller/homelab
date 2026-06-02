# Tailnet Ingress

Tags: #runbooks #networking #tailscale #istio

Source: `docs/networking-tailnet-ingress.md`

## Model

Istio is the reverse proxy for app access. Tailscale is the reachability layer.
Most routes are internal-only. Public Tailscale Funnel is reserved for reviewed
webhook paths that external SaaS systems must reach.

`*.stinkyboi.com` is expected to resolve to the Tailscale-exposed Istio ingress
address from tailnet clients. DNS is not managed by this repo yet.

Octelium is being staged separately as a client bridge and demo under
[[octelium]]. It does not own the current `*.stinkyboi.com` Istio routes and
does not replace the Tailscale exit node.

## Current Route Rules

- Argo CD, Grafana, Kiali, Deluge, Prowlarr, Radarr, Sonarr, LiteLLM,
  OpenClaw, n8n editor/UI, Policy Bot UI and normal routes, and OctoBot UI are
  tailnet-only.
- n8n webhooks are a reviewed public Funnel exception:
  `https://n8n-webhook.tail67beb.ts.net` for production `/webhook` paths only.
- n8n test and waiting webhook paths stay private on the tailnet editor host:
  `https://n8n.stinkyboi.com/webhook-test/...` and
  `https://n8n.stinkyboi.com/webhook-waiting/...`.
- Policy Bot GitHub webhook is another reviewed public Funnel exception:
  `https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook`.
- Prometheus is intentionally not exposed; Grafana is the metrics UI and Kiali
  is the read-only mesh UI.
- OctoBot exposes only `https://octobot.stinkyboi.com` through the tailnet
  gateway. Its exchange credentials and strategy state live on PVC-backed
  runtime configuration, not in public repository files.

## TLS And Certificates

Istio terminates HTTPS with `stinkyboi-com-tls` in `istio-system`.
cert-manager requests the wildcard certificate through
`letsencrypt-cloudflare`, backed by the `cloudflare-api-token` Secret from
External Secrets.

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
