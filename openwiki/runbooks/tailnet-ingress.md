---
type: runbook
title: "Tailnet And App Ingress"
description: "Staged Traefik mesh ingress, private Fleet, reviewed Funnel callbacks, and safe traffic cutover."
tags: [runbook, networking, ingress]
sources:
  - id: openwiki-source-0108413231c2f8b3f2972abd
    resource: repo://clusters/homelab/apps/affine/networkpolicy.yaml
  - id: openwiki-source-812216982d0b6a887bf09651
    resource: repo://clusters/homelab/apps/cordium/networkpolicy.yaml
  - id: openwiki-source-5eb041b69ecfffa36cf7ffbb
    resource: repo://clusters/homelab/apps/n8n/values.yaml
  - id: openwiki-source-d190dbce4c50934f34b78ce1
    resource: repo://clusters/homelab/apps/nofx/networkpolicy.yaml
  - id: openwiki-source-c6350999c9f74bf0f53f9005
    resource: repo://clusters/homelab/apps/octelium-cluster/console-redirect.yaml
  - id: openwiki-source-df94d6406e64c190589692a0
    resource: repo://clusters/homelab/apps/openclaw/networkpolicy.yaml
  - id: openwiki-source-fa98853a4d8b97699eb08972
    resource: repo://clusters/homelab/apps/policy-bot/networkpolicy.yaml
  - id: openwiki-source-8f628fd33437cf63e7f9b8c2
    resource: repo://clusters/homelab/apps/traefik/CUTOVER.md
  - id: openwiki-source-f7b4195d4d622f91da5cc07b
    resource: repo://clusters/homelab/apps/traefik/funnel.yaml
  - id: openwiki-source-ac4e5166b14da067a9c57d03
    resource: repo://clusters/homelab/apps/traefik/networkpolicy.yaml
  - id: openwiki-source-e26a7307e86732ce7e6a34b6
    resource: repo://clusters/homelab/apps/traefik/routes.yaml
  - id: openwiki-source-cc574ebd8a3bf817cd4a4c4b
    resource: repo://clusters/homelab/apps/traefik/values.yaml
  - id: openwiki-source-c071f0a75793c76e7f880496
    resource: repo://clusters/homelab/platform/dns/coredns-configmap.yaml
  - id: openwiki-source-c5bae48eacfc2b48af15ad5a
    resource: repo://scripts/ci/traefik-routes-test.py
  - id: openwiki-source-0f0f64f89adebd3b517b3c98
    resource: repo://scripts/multica-desktop-connect.py
  - id: openwiki-source-a8e2cab0bb2d9f7f664ad849
    resource: repo://scripts/n8n-github-webhooks.py
  - id: openwiki-source-3a59e2e385041c09f8b021a1
    resource: repo://scripts/policy-bot-webhook.py
  - id: openwiki-source-6f8ea3753bc76b21d99fe402
    resource: repo://scripts/tailscale-ci-configure.py
  - id: openwiki-source-c4ba7c9b8c99ef7f9cfb598b
    resource: repo://scripts/tailscale-private-dns.sh
generated: { by: "codex", at: "2026-10-10T20:51:47.381Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-10T20:51:47.381Z
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
The [ingress runbook](../../docs/networking-tailnet-ingress.md) describes the
current staged source and the acceptance required before final retirement.

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
AFFiNE, NOFX, OpenClaw and Policy Bot allow encrypted HBONE on port 15008
separately from cleartext source selectors, leaving workload identity and
destination-port checks to Istio AuthorizationPolicy.
Istio rejects unrelated authenticated mesh principals; unmeshed intra-cluster
callers still require application authentication. Registry source-IP restrictions
have a trusted node-local bypass. Do not claim full east-west isolation.

Publish Traefik's reviewed image, adopt policy through the operator Terraform
unit, then register and verify the GitOps resources. Require Ready certificates,
healthy proxies and actual application access from a mesh client before changing
DNS. Preserve current app state and enrollment URLs; confirm Fleet check-in,
native Cordium execution/reconnection, and uncached node registry pulls.

Switch webhook registrations after public reachability and negative-path checks;
require fresh signed delivery before retiring the former callbacks. Migrate CI to federated mesh identities only after its API proxy,
RBAC and admission boundary are deployed. Retire old DNS, Cloudflare Tunnel and
non-Cordium native Services through their reviewed code paths after all callers
move. Validate a second retirement run is a no-op. Use reviewed reverts and the
owned DNS/node helpers for rollback; never repair live routing by hand.

## Cutover utilities

Follow the [staged cutover](../../clusters/homelab/apps/traefik/CUTOVER.md).
The additive `tailscale-private-dns.sh` previews by default and requires exact
reviewed main to write only its fixed DNS-only A/AAAA inventory. It preserves
legacy CI, callback and carrier names. Phase 2a removes the old DNS-restoration
workflow and writer, preserves their tunnel, and requires verified Talos registry
access. It sends internal API and Harbor DNS to Traefik, advertises n8n's Funnel
URL, and adds the unmeshed Cordium/Traefik peer allowances. Require healthy
Traefik, certificates, both Funnel proxies, and adopted tailnet policy before
that GitOps change; n8n can re-register external hooks when it restarts.
Before DNS preflight, `multica-desktop-connect.py --resume-only` reconnects only
the verified saved tailnet profile and checks the ingress peer; it leaves
Desktop credentials and the local carrier unchanged.
After DNS readback, the Mac helper migrates the verified existing account while
preserving credentials and owned-file rollback. Wait the reported former TTL,
then explicitly verify normal DNS, canonical TLS and native gRPC. Only then
merge phase 2b, which moves CI workflows and shared native operator transport
after the provider-owned identity bindings have been published.

The callback helpers change only the fixed n8n hooks and Policy Bot App webhook
URL. Non-executing preflights protect live workflows; private local receipts
require both a newer delivery ID and timestamp after cutover. Historical success
cannot satisfy acceptance. The CI publisher reads three non-secret provider
outputs and reconciles only their declared GitHub variables after checking
signed current main and environment protection. These utilities do not switch
CI workflows or retire the native catalog by themselves.

See [Validation Gates](../operations/validation-gates.md),
[Secrets And Identity](../architecture/secrets-and-identity.md), and
[Workload Inventory](../workloads/inventory.md).
