# Tailnet Ingress

Octelium is the primary access plane for homelab apps, VPN sessions, CI
Kubernetes API reachability, and external callback paths. Existing
`*.stinkyboi.com` app hostnames resolve through the repo-owned
`octelium-public` Cloudflare Tunnel connector. Octelium `WEB` Services normally
enforce clientless browser login before proxying to the existing private Istio
routes. AFFiNE is anonymous at Octelium and uses its own authentication so its
stock native client can connect. Tailscale Funnel is not an approved
external-service backbone in steady state.

## DNS Model

Exact app, callback, and Octelium control-plane records such as
`grafana.stinkyboi.com`, `n8n-webhook.stinkyboi.com`,
`policy-bot-hook.stinkyboi.com`, `portal.stinkyboi.com`, and
`octelium-api.stinkyboi.com` must be proxied CNAMEs to the
`homelab-octelium-public` Cloudflare Tunnel target,
`<tunnel-uuid>.cfargotunnel.com`. Public DNS answers should be Cloudflare
anycast addresses, not Octelium private service IPs or the old tailnet
LoadBalancer IP. Use `scripts/octelium-public-dns.sh` to reconcile those exact
records from the SSM-backed tunnel UUID.

The public tunnel forwards app UI hostnames to the Octelium public ingress
dataplane so Octelium can select the matching `WEB` Service and apply its
declared clientless or anonymous access mode.
The tunnel forwards the Octelium Cluster/API/portal hostnames, Enterprise
console, and unauthenticated callback hostnames to the in-cluster Istio gateway,
where explicit `VirtualService` objects keep backend routing narrow.

Cloudflare edge TLS and the origin certificate must cover the apex plus
first-level `*.stinkyboi.com` names. That free Cloudflare certificate shape is
why `stinkyboi.com` is the Octelium cluster domain even though
`octelium.stinkyboi.com` remains a public alias.

## Route Inventory

| Surface | HTTPS host | Backbone |
|-----|------------------|---------------|
| Octelium control plane | `https://stinkyboi.com`, `https://octelium.stinkyboi.com`, `https://portal.stinkyboi.com`, `https://octelium-api.stinkyboi.com` | `octelium-public` Cloudflare Tunnel to Istio/Octelium |
| app UIs | existing `https://*.stinkyboi.com` app hostnames | `octelium-public` Cloudflare Tunnel to Octelium `WEB` Services; clientless except AFFiNE |
| n8n webhooks | `https://n8n-webhook.stinkyboi.com/webhook...` | `octelium-public` Cloudflare Tunnel to Istio, limited to webhook prefixes |
| Policy Bot GitHub webhook | `https://policy-bot-hook.stinkyboi.com/api/github/hook` | `octelium-public` Cloudflare Tunnel to Istio, limited to `/api/github/hook` |

Istio terminates HTTPS with the `stinkyboi-com-tls` certificate in
`istio-system`. cert-manager requests this wildcard certificate through the
`letsencrypt-cloudflare` ClusterIssuer, which uses DNS-01 challenges for
`stinkyboi.com` and reads its Cloudflare token from the External Secrets-managed
`cloudflare-api-token` Secret in the `cert-manager` namespace. The certificate
includes `stinkyboi.com` and `*.stinkyboi.com` so Istio origin TLS covers the
Octelium domain, API, portal, alias, and app backend routes. The
`homelab-selfsigned` issuer
remains available only as a local fallback and is not referenced by the ingress
wildcard certificate.

The rendered Conftest policy rejects Tailscale Funnel and requires every public
Istio `VirtualService`, public `Gateway`, or non-discovery `Ingress` to declare
`homelab.rst.io/access-plane: octelium` unless a future PR intentionally changes
the policy. Unauthenticated callback routes must also carry
`homelab.rst.io/public-callback: "true"`,
`homelab.rst.io/public-callback-reviewed: "true"`, and a non-empty
`homelab.rst.io/public-callback-purpose`.

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

Octelium serves the app UI set through
`docs/examples/octelium/homelab-services.yaml` with service names in the
`homelab` Octelium namespace. External SaaS callbacks that cannot perform an
Octelium browser login use explicit first-level callback hostnames through the
same `octelium-public` tunnel, not Tailscale Funnel.

AFFiNE uses `https://affine.stinkyboi.com` through the public, anonymous
Octelium `affine` WEB Service. The Cloudflare Tunnel forwards that hostname to
the Octelium ingress dataplane and then the Istio route. AFFiNE authenticates
users itself, registration is disabled after bootstrap, and the anonymous
transport lets AFFiNE Desktop use its native-origin CORS flow.

Use `https://octobot.stinkyboi.com` through Octelium for private setup, paper
trading, and operator-reviewed live trading; exchange credentials and strategy
state are configured through OctoBot and persist on its NFS-backed volumes, not
in public repository files.

Compass launch links and discovery-only entries point at the public
Octelium-fronted `*.stinkyboi.com` app URLs. It discovers Kubernetes ingress
and Gateway API routes with read-only RBAC, disables operator debug routes, and
does not persist application state.

Because the homelab's reviewed ingress path is still Istio `VirtualService`,
Compass also owns discovery-only `Ingress` resources in the `monitoring`
namespace. Those resources use the inert `compass-discovery` IngressClass and
carry the same hostnames and Compass metadata for catalog discovery, but they
do not route traffic. They are annotated with
`argocd.argoproj.io/ignore-healthcheck: "true"` because no ingress controller
is expected to populate `status.loadBalancer` for the inert class; the Compass
Deployment remains the operational health signal.

## Secondary Tailnet Exit Node And LAN Route

Octelium is the primary VPN and access system for users and CI. Tailscale
remains a secondary LAN/egress utility rather than the app, callback, or GitHub
Actions backbone. The `tailscale` Argo CD Application installs the upstream
Tailscale Kubernetes Operator and applies the repo-owned `homelab-exit-node`
`Connector` from `clusters/homelab/apps/tailscale/exit-node-connector.yaml`.

The connector is cluster-scoped, creates one operator-managed proxy device, and
advertises that device as a Tailscale exit node with hostname
`homelab-exit-node` and tag `tag:k8s`. Tailnet clients can select that device as
their exit node to route internet-bound traffic through the homelab cluster
egress path. It also advertises the `10.1.0.0/24` homelab LAN route so tailnet
clients can reach local network services through the same operator-managed
device when Octelium is unavailable or when a local-LAN workflow has not yet
moved. GitHub Actions uses Octelium Service `kubernetes-api.ci` instead of this
tailnet route.

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

## Policy Bot Webhook Callback

Policy Bot must receive GitHub App webhook deliveries from outside the tailnet.
The reviewed public route is:

```text
Owning application: policy-bot
Public path: /api/github/hook
Purpose: GitHub App webhook deliveries for pull request policy evaluation.
Source system: GitHub App webhooks.
Authentication or signature check: policy-bot validates the GitHub webhook HMAC
secret from /homelab/policy-bot/github-app/webhook-secret.
Public callback hostname: policy-bot-hook.stinkyboi.com
Backbone: octelium-public Cloudflare Tunnel to the shared Istio gateway.
Rollback command: revert clusters/homelab/apps/policy-bot/virtualservice-webhook.yaml
or remove it from kustomization.yaml, remove the hostname from
octelium-public, then sync the policy-bot and octelium-public Applications.
Data exposed: webhook request body and headers sent by GitHub.
```

The Policy Bot UI, details routes, static assets, OAuth callback, and root path
target `https://policy-bot.stinkyboi.com` through Octelium. Only
`/api/github/hook` is exposed through the public callback host.
After rollout, update the GitHub App webhook URL to this hostname.

## n8n Webhook Callback

n8n must advertise webhook URLs that external SaaS systems can call. The
reviewed public route is:

```text
Owning application: n8n
Public paths: /webhook, /webhook-test, /webhook-waiting
Purpose: n8n workflow webhook deliveries from external systems.
Source system: workflow-specific SaaS integrations and HTTP clients configured in n8n.
Authentication or signature check: workflow-specific n8n webhook credentials, node-level signing, or path entropy where configured.
Public callback hostname: n8n-webhook.stinkyboi.com
Backbone: octelium-public Cloudflare Tunnel to the shared Istio gateway.
Rollback command: revert clusters/homelab/apps/n8n/virtualservice.yaml and the WEBHOOK_URL change, remove the hostname from octelium-public, then sync the n8n and octelium-public Applications.
Data exposed: request bodies and headers sent to active n8n webhook workflows.
```

The n8n editor, REST API, static assets, and root path target
`https://n8n.stinkyboi.com` through Octelium. The callback VirtualService only
routes webhook path prefixes on `n8n-webhook.stinkyboi.com`.
After rollout, update external callers that still use the retired Funnel URL to
the new callback hostname.

## Future Callback Template

Future public exposure must be limited to callback paths, reviewed separately,
and routed through the Octelium public connector unless a later policy change
explicitly approves another backbone.

```text
Owning application:
Public path:
Purpose:
Source system:
Authentication or signature check:
Public callback hostname:
Backbone:
Rollback command:
Data exposed:
```
