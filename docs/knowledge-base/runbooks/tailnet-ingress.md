# Tailnet Ingress

Tags: #runbooks #networking #tailscale #istio

Source: `docs/networking-tailnet-ingress.md`

## Model

Istio is the reverse proxy for app access. Tailscale is the reachability layer.
Most routes are internal-only. Public Tailscale Funnel is reserved for reviewed
webhook paths that external SaaS systems must reach.

`*.stinkyboi.com` is expected to resolve to the Tailscale-exposed Istio ingress
address from tailnet clients. DNS is not managed by this repo yet.

## Current Route Rules

- Argo CD, Grafana, Deluge, Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, n8n,
  Policy Bot UI, and OctoBot UI are tailnet-only.
- Policy Bot GitHub webhook is the reviewed public Funnel exception:
  `https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook`.
- Prometheus is intentionally not exposed; Grafana is the metrics UI.
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
with tag `tag:k8s` and advertises `10.1.0.199/32` for CI access to the
Kubernetes API.

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
