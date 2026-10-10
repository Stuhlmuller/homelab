---
type: runbook
title: "Tailnet And App Ingress"
description: "Staged Traefik mesh ingress, private Fleet, reviewed Funnel callbacks, and safe traffic cutover."
tags: [runbook, networking, ingress]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T18:57:48.826Z
sources:
  - id: openwiki-source-c6350999c9f74bf0f53f9005
    resource: repo://clusters/homelab/apps/octelium-cluster/console-redirect.yaml
  - id: openwiki-source-f7b4195d4d622f91da5cc07b
    resource: repo://clusters/homelab/apps/traefik/funnel.yaml
  - id: openwiki-source-e26a7307e86732ce7e6a34b6
    resource: repo://clusters/homelab/apps/traefik/routes.yaml
  - id: openwiki-source-cc574ebd8a3bf817cd4a4c4b
    resource: repo://clusters/homelab/apps/traefik/values.yaml
generated: { by: "codex", at: "2026-10-10T18:57:48.826Z" }
---

# Tailnet And App Ingress

The migration foundation declares Traefik as the reverse proxy for private
application URLs. Fleet devices and administrators use the Tailscale mesh;
Fleet has no Funnel route. Octelium remains for Cordium and its required portal,
API and console. Existing DNS and Cloudflare transport remain until cutover
acceptance; foundation source alone does not establish deployed traffic changes.

Canonical desired state and validation:
[Traefik README](../../clusters/homelab/apps/traefik/README.md),
[route inventory](../../clusters/homelab/apps/traefik/routes.yaml), and
[Tailscale provider runbook](../../IaC/modules/tailscale-access/README.md).
The older [ingress runbook](../../docs/networking-tailnet-ingress.md) describes
the retained migration source path until its traffic-cutover revision lands.

```mermaid
flowchart LR
    Client[Mesh client] --> Private[Tailscale private proxy]
    Private --> TLS[Traefik private TLS listener]
    TLS --> Apps[Application Services]
    TLS --> Cordium[Octelium Cordium and control]
    Public[Public callback] --> Funnel[Tailscale Funnel]
    Funnel --> HTTP[Traefik callback listener]
    HTTP --> Hooks[n8n and Policy Bot webhooks]
    Nodes[Talos nodes] --> Registry[Traefik registry listener]
    Registry --> Harbor[Harbor OCI and token endpoints]
```

Separate listeners prevent public callbacks from selecting private routers.

## Route boundaries

`traefik-private` receives mesh traffic for the existing private custom hostnames;
cert-manager supplies their public-trust TLS certificate. `homelab-ingress` is
the Tailscale device name. Explicit file-provider routes select fixed Services;
Traefik does not discover arbitrary workloads. Fleet's setup paths remain denied.

Only `n8n-webhook.tail67beb.ts.net` and `policy-bot-hook.tail67beb.ts.net` use
Funnel. The former accepts the three declared webhook path families; the latter
accepts exactly `/api/github/hook`. Application webhook authentication remains
required. Root/admin paths and spoofed private Host headers fail at the callback
listener. Encoded reserved path characters are rejected on these sensitive routes.

Cordium and native Octelium API paths retain WebSockets and h2c. The console alone
uses the existing Istio HTTPS gateway with verified upstream SNI to preserve its
conditional login-redirect correction. This retained control dependency is
separate from the direct application proxy routes.

Talos uses a dedicated `10.96.0.50:443` registry Service and host-only DNS patch;
see [Harbor](../operations/harbor-oci.md). It exposes OCI/token paths only, not
Harbor management or unrelated application hosts.

## Security and rollout gates

Traefik joins ambient and app authorization policies trust its dedicated service
account. Tailscale ACLs govern external mesh access. Flannel does not enforce the
NetworkPolicy manifests: they express intended peers, not current isolation.
Istio rejects unrelated authenticated mesh principals; unmeshed intra-cluster
callers still require application authentication. Registry source-IP restrictions
have a trusted node-local bypass. Do not claim full east-west isolation.

Publish Traefik's reviewed image, adopt policy through the operator Terraform
unit, then register and verify the GitOps resources. Require Ready certificates,
healthy proxies and actual application access from a mesh client before changing
DNS. Preserve current app state and enrollment URLs; confirm Fleet check-in,
native Cordium execution/reconnection, and uncached node registry pulls.

Switch webhook registrations only after signed delivery and public negative-path
checks succeed. Migrate CI to federated mesh identities only after its API proxy,
RBAC and admission boundary are deployed. Retire old DNS, Cloudflare Tunnel and
non-Cordium native Services through their reviewed code paths after all callers
move. Validate a second retirement run is a no-op. Use reviewed reverts and the
owned DNS/node helpers for rollback; never repair live routing by hand.

See [Validation Gates](../operations/validation-gates.md),
[Secrets And Identity](../architecture/secrets-and-identity.md), and
[Workload Inventory](../workloads/inventory.md).
