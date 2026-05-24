# Tailnet Ingress

Istio is the reverse proxy for this onboarding. Tailscale is the reachability
layer. The first rollout is internal-only: no Tailscale Funnel routes are
enabled.

## Initial DNS Assumption

The repository expects one initial DNS or tailnet naming setup that covers all
internal app routes. For this homelab, `*.stinkyboi.com` must resolve to the
Tailscale-exposed Istio ingress address from tailnet clients. This feature does
not add or edit public DNS records after that initial setup.

Because no DNS provider resources are added in this repository, external DNS
infrastructure is unaffected by this change. If DNS becomes repo-managed later,
that must be added through a separate Terragrunt/OpenTofu entry point.

## First-Rollout Route Inventory

| App | HTTPS host | Public Funnel |
|-----|------------------|---------------|
| prometheus | `https://prometheus.stinkyboi.com` | disabled |
| grafana | `https://grafana.stinkyboi.com` | disabled |
| deluge | `https://deluge.stinkyboi.com` | disabled |
| radarr | `https://radarr.stinkyboi.com` | disabled |
| sonarr | `https://sonarr.stinkyboi.com` | disabled |
| litellm | `https://litellm.stinkyboi.com` | disabled |
| openclaw | `https://openclaw.stinkyboi.com` | disabled |
| tines | `https://tines.stinkyboi.com` | disabled |

Istio terminates HTTPS with the `stinkyboi-com-tls` certificate in
`istio-system`. The first rollout uses the existing self-signed homelab issuer;
replace the issuer through desired state before relying on browser-trusted TLS.

Validation on 2026-05-24 found no enabled first-rollout Funnel routes. The
Istio gateway and every VirtualService route manifest are annotated with
`homelab.rst.io/public-funnel: "false"`.

## Future Funnel Webhook Exception Template

Future public exposure must be limited to webhook paths and reviewed separately.

```text
Owning application:
Public path:
Purpose:
Source system:
Authentication or signature check:
Tailscale Funnel hostname:
Rollback command:
Data exposed:
```
