# Tailnet Ingress

Tags: #runbooks #networking #tailscale #istio

Source: `docs/networking-tailnet-ingress.md`

## Model

Octelium is the target access plane for human app access. Istio plus Tailscale
remain the fallback app route until `scripts/octelium-e2e-check.sh` proves the
Octelium Cluster, service catalog, connector, and client tunnel work end to
end. Public Tailscale Funnel is reserved for reviewed webhook paths that
external SaaS systems must reach.

`*.stinkyboi.com` is expected to resolve to the Tailscale-exposed Istio ingress
address from tailnet clients while those fallback routes remain. DNS is not
managed by this repo yet.

Octelium is documented under [[octelium]] for the same private homelab service
set. It replaces app access only after the e2e gate passes; it does not
automatically replace the Tailscale exit node, CI route, or reviewed public
webhook exceptions.

## Current Route Rules

- Argo CD, Grafana, Kiali, Deluge, Prowlarr, Radarr, Sonarr, LiteLLM,
  OpenClaw, n8n editor/UI, Policy Bot UI and normal routes, and OctoBot UI
  still have tailnet-only fallback routes.
- n8n webhooks are a reviewed public Funnel exception:
  `https://n8n-webhook.tail67beb.ts.net` for `/webhook`, `/webhook-test`, and
  `/webhook-waiting` only.
- Policy Bot GitHub webhook is another reviewed public Funnel exception:
  `https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook`.
- Prometheus is intentionally not exposed; Grafana is the metrics UI and Kiali
  is the read-only mesh UI.
- OctoBot uses `octobot.homelab` through Octelium after cutover; the
  `https://octobot.stinkyboi.com` route is fallback until the gate passes. Its
  exchange credentials and strategy state live on PVC-backed runtime
  configuration, not in public repository files.
- Octelium serves private WEB Services from
  `docs/examples/octelium/homelab-services.yaml`; public webhook callbacks stay
  on their reviewed Tailscale Funnel exceptions until separately redesigned.

## TLS And Certificates

Istio terminates HTTPS with `stinkyboi-com-tls` in `istio-system`.
cert-manager requests the wildcard certificate through
`letsencrypt-cloudflare`, backed by the `cloudflare-api-token` Secret from
External Secrets. The certificate also includes `*.octelium.stinkyboi.com` for
the nested Octelium API/portal bootstrap names; the existing `*.stinkyboi.com`
SAN already covers the `octelium.stinkyboi.com` Cluster domain.

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
