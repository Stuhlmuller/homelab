# Tailnet Ingress

Istio is the reverse proxy for tailnet app access. Tailscale is the
reachability layer. Most routes are internal-only; public Tailscale Funnel is
reserved for reviewed webhook paths that must be reachable by external SaaS
systems.

Octelium is documented separately in `docs/octelium.md` as a parallel client
bridge for the same private homelab service set. It does not replace the
Tailscale operator, tailnet gateway, Funnel exceptions, or homelab exit node in
this runbook.

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
| argocd | `https://argocd.stinkyboi.com` | disabled |
| grafana | `https://grafana.stinkyboi.com` | disabled |
| kiali | `https://kiali.stinkyboi.com` | disabled |
| compass | `https://compass.stinkyboi.com` | disabled |
| deluge | `https://deluge.stinkyboi.com` | disabled |
| prowlarr | `https://prowlarr.stinkyboi.com` | disabled |
| radarr | `https://radarr.stinkyboi.com` | disabled |
| sonarr | `https://sonarr.stinkyboi.com` | disabled |
| litellm | `https://litellm.stinkyboi.com` | disabled |
| openclaw | `https://openclaw.stinkyboi.com` | disabled |
| n8n editor/UI | `https://n8n.stinkyboi.com` | disabled |
| n8n webhooks | `https://n8n-webhook.tail67beb.ts.net/webhook...` | enabled for `/webhook`, `/webhook-test`, and `/webhook-waiting` only |
| policy-bot UI and normal routes | `https://policy-bot.stinkyboi.com` | disabled |
| octobot UI | `https://octobot.stinkyboi.com` | disabled |
| policy-bot GitHub webhook | `https://policy-bot-hook.<tailnet-name>.ts.net/api/github/hook` | enabled for `/api/github/hook` only |

Istio terminates HTTPS with the `stinkyboi-com-tls` certificate in
`istio-system`. cert-manager requests this wildcard certificate through the
`letsencrypt-cloudflare` ClusterIssuer, which uses DNS-01 challenges for
`stinkyboi.com` and reads its Cloudflare token from the External Secrets-managed
`cloudflare-api-token` Secret in the `cert-manager` namespace. The certificate
also includes `*.octelium.stinkyboi.com` for the nested Octelium API/portal
bootstrap names; the existing `*.stinkyboi.com` SAN already covers the
`octelium.stinkyboi.com` Cluster domain. The `homelab-selfsigned` issuer
remains available only as a local fallback and is not referenced by the ingress
wildcard certificate.

Validation on 2026-05-24 found no enabled first-rollout Funnel routes. Policy
Bot later added a reviewed Funnel exception for GitHub webhook delivery, and
n8n now adds a reviewed Funnel exception for workflow webhook delivery. The
`policy-bot-hook-funnel` and `n8n-webhook-funnel` Tailscale Ingresses are
annotated with `homelab.rst.io/public-funnel: "true"` and
`homelab.rst.io/public-funnel-reviewed: "true"`; the Policy Bot UI and n8n
editor routes remain private. Every other Istio gateway and VirtualService
route manifest remains tailnet-only.

The Istio ingressgateway Service is a Tailscale `LoadBalancer` and sets
`allocateLoadBalancerNodePorts: false` so the gateway is not exposed through
high NodePorts on every Talos node. A 2026-05-25 read-only scan found existing
NodePorts from the earlier Service revision. After Argo CD syncs this desired
state, verify those ports are gone with `kubectl -n istio-system get svc
istio-ingressgateway -o yaml` and a focused node-port scan.

Prometheus is intentionally absent from the tailnet route inventory. Grafana is
the reviewed metrics UI, and Kiali is the reviewed read-only mesh UI. Direct
Prometheus ingress must not be restored without a documented authentication plan
and rollback path.

Octelium serves the private app set through
`docs/examples/octelium/homelab-services.yaml` with service names in the
`homelab` Octelium namespace. Keep public Funnel exceptions and Octelium
Services separate: the n8n and Policy Bot webhook paths remain Tailscale Funnel
exceptions unless a later PR explicitly redesigns those callbacks through
Octelium.

OctoBot exposes its UI only through the tailnet Istio route at
`https://octobot.stinkyboi.com`. The route is intended for private setup,
paper trading, and operator-reviewed live trading; exchange credentials and
strategy state are configured through OctoBot and persist on its NFS-backed
volumes, not in public repository files.

Compass exposes the service catalog only through the tailnet Istio route at
`https://compass.stinkyboi.com`. It discovers Kubernetes ingress and Gateway API
routes with read-only RBAC, disables operator debug routes, and does not persist
application state.

Because the homelab's reviewed ingress path is still Istio `VirtualService`,
Compass also owns discovery-only `Ingress` resources in the `monitoring`
namespace. Those resources use the inert `compass-discovery` IngressClass and
carry the same hostnames and Compass metadata for catalog discovery, but they
do not replace the Istio `VirtualService` resources that route traffic through
`tailnet-gateway`.

## Homelab VPN Exit Node And LAN Route

Tailscale also provides the homelab VPN exit path. The `tailscale` Argo CD
Application installs the upstream Tailscale Kubernetes Operator and applies the
repo-owned `homelab-exit-node` `Connector` from
`clusters/homelab/apps/tailscale/exit-node-connector.yaml`.

The connector is cluster-scoped, creates one operator-managed proxy device, and
advertises that device as a Tailscale exit node with hostname
`homelab-exit-node` and tag `tag:k8s`. Tailnet clients can select that device as
their exit node to route internet-bound traffic through the homelab cluster
egress path. It also advertises the `10.1.0.0/24` homelab LAN route so tailnet
clients can reach local network services through the same operator-managed
device. CI/CD grants still restrict GitHub-hosted runners to the Kubernetes API
at `10.1.0.199:6443`.

This repository cannot approve tailnet routes by itself. The tailnet policy must
allow `tag:k8s-operator` to own `tag:k8s`, and either auto-approve exit-node
and `10.1.0.0/24` route advertisement for `tag:k8s`, or rely on an admin
manually approving `homelab-exit-node` and the advertised route in the Tailscale
Machines page after sync.

Validate the exit node after Argo CD syncs Tailscale:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=homelab-exit-node
```

Expected result: the connector reports exit-node status and the
`10.1.0.0/24` subnet route, its ready condition is true, and a single Tailscale
proxy Pod is running. Then select `homelab-exit-node` on a client and verify the
public egress IP changes to the homelab network while homelab LAN addresses in
`10.1.0.0/24` remain reachable. Keep local-network access enabled on clients
that still need their nearby LAN access while using the exit node.

## Policy Bot Webhook Funnel Exception

Policy Bot must receive GitHub App webhook deliveries from outside the tailnet.
The reviewed public route is:

```text
Owning application: policy-bot
Public path: /api/github/hook
Purpose: GitHub App webhook deliveries for pull request policy evaluation.
Source system: GitHub App webhooks.
Authentication or signature check: policy-bot validates the GitHub webhook HMAC
secret from /homelab/policy-bot/github-app/webhook-secret.
Tailscale Funnel hostname: policy-bot-hook.<tailnet-name>.ts.net
Rollback command: revert clusters/homelab/apps/policy-bot/ingress-funnel.yaml
or remove it from kustomization.yaml, then sync the policy-bot Application.
Data exposed: webhook request body and headers sent by GitHub.
```

The Policy Bot UI, details routes, static assets, OAuth callback, and root path
stay on `https://policy-bot.stinkyboi.com` through the tailnet-only Istio
gateway. Only `/api/github/hook` is exposed through Funnel.

## n8n Webhook Funnel Exception

n8n must advertise webhook URLs that external SaaS systems can call. The
reviewed public route is:

```text
Owning application: n8n
Public paths: /webhook, /webhook-test, /webhook-waiting
Purpose: n8n workflow webhook deliveries from external systems.
Source system: workflow-specific SaaS integrations and HTTP clients configured in n8n.
Authentication or signature check: workflow-specific n8n webhook credentials, node-level signing, or path entropy where configured.
Tailscale Funnel hostname: n8n-webhook.tail67beb.ts.net
Rollback command: revert clusters/homelab/apps/n8n/ingress-funnel.yaml, clusters/homelab/apps/n8n/gateway-funnel.yaml, and the WEBHOOK_URL change, then sync the n8n Application.
Data exposed: request bodies and headers sent to active n8n webhook workflows.
```

The n8n editor, REST API, static assets, and root path stay on
`https://n8n.stinkyboi.com` through the tailnet-only Istio gateway. The Funnel
Ingress forwards only webhook path prefixes to the Istio gateway, and the n8n
VirtualService only routes those prefixes on the public webhook gateway.

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
