# Tailnet Ingress

Istio is the reverse proxy for this onboarding. Tailscale is the reachability
layer. The first rollout is internal-only: no Tailscale Funnel routes are
enabled.

## Initial DNS Assumption

The repository expects one initial DNS or tailnet naming setup that covers all
internal app routes, such as a wildcard record for `*.apps.tailnet.example` or
an equivalent Tailscale-native naming pattern. This feature does not add or edit
public DNS records after that initial setup.

Because no DNS provider resources are added in this repository, external DNS
infrastructure is unaffected by this change. If DNS becomes repo-managed later,
that must be added through a separate Terragrunt/OpenTofu entry point.

## First-Rollout Route Inventory

| App | Host placeholder | Public Funnel |
|-----|------------------|---------------|
| grafana | `grafana.apps.tailnet.example` | disabled |
| deluge | `deluge.apps.tailnet.example` | disabled |
| radarr | `radarr.apps.tailnet.example` | disabled |
| sonarr | `sonarr.apps.tailnet.example` | disabled |
| litellm | `litellm.apps.tailnet.example` | disabled |
| openclaw | `openclaw.apps.tailnet.example` | disabled |
| tines | `tines.apps.tailnet.example` | disabled |

The placeholder domain is intentionally public-safe. Replace it through the
initial DNS/tailnet configuration before live rollout.

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
