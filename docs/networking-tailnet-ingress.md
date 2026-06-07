# Tailnet Ingress

Octelium is the access plane for human access to homelab apps. Existing
`*.stinkyboi.com` app hostnames resolve to Octelium private service IPs after
`scripts/octelium-e2e-check.sh` proves that the Octelium Cluster, service
catalog, connector, and client tunnel all work end to end. Public Tailscale
Funnel remains reserved for reviewed webhook paths that must be reachable by
external SaaS systems until those callbacks are explicitly redesigned.

## DNS Model

Exact app records such as `grafana.stinkyboi.com` and `argocd.stinkyboi.com`
point at Octelium private service IPs, not the old Tailscale wildcard. The
Octelium Cluster names `octelium.stinkyboi.com`,
`portal.octelium.stinkyboi.com`, and `octelium-api.octelium.stinkyboi.com`
are the public bootstrap and control-plane exception: Cloudflare Tunnel routes
those names from the public Internet to the in-cluster Istio gateway, and Istio
then routes to the Octelium dataplane.

The public control-plane DNS records must be exact CNAMEs to the
`homelab-octelium-public` Cloudflare Tunnel target,
`<tunnel-uuid>.cfargotunnel.com`. They must not point at the old tailnet
LoadBalancer IP.

## Route Inventory

| App | HTTPS host | Public Funnel |
|-----|------------------|---------------|
| Octelium control plane | `https://octelium.stinkyboi.com`, `https://portal.octelium.stinkyboi.com`, `https://octelium-api.octelium.stinkyboi.com` | disabled; public access uses Cloudflare Tunnel, not Tailscale Funnel |
| app UIs | existing `https://*.stinkyboi.com` app hostnames | disabled; app access is through Octelium private Services |
| n8n webhooks | `https://n8n-webhook.tail67beb.ts.net/webhook...` | enabled for `/webhook`, `/webhook-test`, and `/webhook-waiting` only |
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
editor routes remain private through Octelium. Other app `VirtualService`
objects are retained only as private Istio backend routes for Octelium TCP/443
Services, with `homelab.rst.io/access-plane: octelium` and public Funnel
disabled.

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
Services separate: the n8n and Policy Bot webhook paths remain Tailscale
Funnel exceptions unless a later PR explicitly redesigns those callbacks
through Octelium.

Use `octobot.homelab` through Octelium for private setup, paper trading, and
operator-reviewed live trading; exchange credentials and strategy state are
configured through OctoBot and persist on its NFS-backed volumes, not in public
repository files.

Compass launch links and discovery-only entries point at Octelium service names.
It discovers Kubernetes ingress and Gateway API routes with read-only RBAC,
disables operator debug routes, and does not persist application state.

Because the homelab's reviewed ingress path is still Istio `VirtualService`,
Compass also owns discovery-only `Ingress` resources in the `monitoring`
namespace. Those resources use the inert `compass-discovery` IngressClass and
carry the same hostnames and Compass metadata for catalog discovery, but they
do not route traffic. They are annotated with
`argocd.argoproj.io/ignore-healthcheck: "true"` because no ingress controller
is expected to populate `status.loadBalancer` for the inert class; the Compass
Deployment remains the operational health signal.

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
target `policy-bot.homelab` through Octelium. Only `/api/github/hook` is
exposed through Funnel.

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

The n8n editor, REST API, static assets, and root path target `n8n.homelab`
through Octelium. The Funnel Ingress forwards only webhook path prefixes to the
Istio gateway, and the n8n VirtualService only routes those prefixes on the
public webhook gateway.

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
