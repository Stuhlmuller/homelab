# Octelium Access And Tailnet Fallback

Octelium is the primary access plane for homelab apps, human and CI Kubernetes
API reachability, private Service sessions, Cordium Workspaces, and external
callback paths. Existing
`*.stinkyboi.com` app hostnames resolve through the repo-owned
`octelium-public` Cloudflare Tunnel connector, including the browser API and native TCP carrier. Octelium `WEB` Services normally
enforce clientless browser login before proxying to the existing private Istio
routes. AFFiNE is anonymous at Octelium so its stock native client can use
application authentication. NOFX requires Octelium login before its own login.
Tailscale Funnel is not an approved external-service backbone in steady state.

## DNS Model

Exact app, callback, and browser control-plane records such as
`grafana.stinkyboi.com`, `n8n-webhook.stinkyboi.com`,
`policy-bot-hook.stinkyboi.com`, and `portal.stinkyboi.com` must be proxied
CNAMEs to the `homelab-octelium-public` Cloudflare Tunnel target,
`<tunnel-uuid>.cfargotunnel.com`. Public DNS answers should be Cloudflare
anycast addresses, not Octelium private service IPs or the old tailnet
LoadBalancer IP.

The API uses two outbound Cloudflare Tunnel routes. Browser gRPC-Web uses
`octelium-api.stinkyboi.com` over HTTPS. Native Octelium and Cordium clients
use `octelium-transport.stinkyboi.com`, a TCP-over-WebSocket carrier to the
existing API-only Istio TLS gateway. Both DNS records are proxied CNAMEs to
`<tunnel-uuid>.cfargotunnel.com`. No router forward or WAN address is required.
The inner connection retains `octelium-api.stinkyboi.com` for certificate
verification, HTTP/2, and Octelium authentication.

Cloudflare does not support native gRPC on public HTTP Tunnel routes. Its
[supported TCP carrier](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/)
transports the TLS stream instead. Cloudflare warns that long-lived carrier
connections can disconnect; require real Cordium execution, terminal streaming,
and reconnect tests before treating this as a proven execution transport.
An account policy requiring Cloudflare Access may add a separate login gate;
the carrier does not grant Octelium authorization.

Inside Kubernetes, `platform-dns` rewrites the same API hostname to the
dedicated `octelium-api-ingressgateway` Service. Clients keep the original
hostname for TLS and SNI while bypassing the public Tunnel carrier. This
split-horizon route is cluster-only; public DNS remains unchanged.

The public tunnel forwards app UI hostnames to the Octelium public ingress
dataplane so Octelium can select the matching `WEB` Service and apply its
declared clientless or anonymous access mode.
The tunnel forwards the Octelium Cluster and portal browser hostnames,
Enterprise console, and unauthenticated callback hostnames to the in-cluster
Istio gateway, where explicit `VirtualService` objects keep backend routing
narrow.

The Istio origin certificate covers the apex plus first-level
`*.stinkyboi.com` names. Cloudflare edge TLS must additionally cover Cordium's
`*.cordium.stinkyboi.com` workspace hosts. Universal SSL does not cover that
second level; provision an advanced edge certificate with the nested wildcard.
Total TLS does not issue certificates for Cloudflare Tunnel hostnames.

## Route Inventory

| Surface | HTTPS host | Backbone |
| --- | --- | --- |
| Octelium browser control plane | `https://stinkyboi.com`, `https://octelium.stinkyboi.com`, `https://portal.stinkyboi.com` | `octelium-public` Cloudflare Tunnel to Istio/Octelium |
| Octelium CLI API | `https://octelium-api.stinkyboi.com` | Browser gRPC-Web over HTTPS Tunnel; native TLS gRPC over the `octelium-transport.stinkyboi.com` TCP Tunnel carrier |
| Kubernetes API for humans and Cordium | private Service `kubernetes-api.homelab` | `octelium connect`, then `octelium config kubernetes-api.homelab`; Cordium Workspaces already have a restricted read-only client session |
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

The rendered Conftest policy rejects Tailscale Funnel and treats every Istio
`VirtualService` attached to a gateway other than `mesh`, every `Gateway`, and
every `Ingress` except the explicit `compass-discovery` class as externally
reachable by default. Those resources must declare
`homelab.rst.io/access-plane: octelium`; only gatewayless or mesh-only
`VirtualService` resources and Compass discovery entries are exempt.
Unauthenticated callback routes must also carry
`homelab.rst.io/public-callback: "true"`,
`homelab.rst.io/public-callback-reviewed: "true"`, and a non-empty
`homelab.rst.io/public-callback-purpose`.

The primary `istio-ingressgateway` Service is `ClusterIP` only and has no
Tailscale LoadBalancer. Octelium service proxies and `octelium-public` reach it
through cluster DNS, so app routes cannot bypass Octelium through a tailnet
device. The existing `tailnet-gateway` object keeps its legacy name but is only
an internal Istio TLS-routing resource. A separate gateway-chart release and
`octelium-api-gateway` TLS configuration expose fixed NodePort `30443`. Its
workload selector and API-only `VirtualService` are separate from
`tailnet-gateway`, preventing another app hostname from using the WAN listener.
After Argo CD loads the new `octelium-public` pod revision, run the protected
workflow to remove the retired WAN origin rules and reconcile Tunnel DNS:

```sh
gh workflow run octelium-public-tunnel.yml --ref main -f expected_sha='<reviewed-main-sha>'
nix develop --command python3 scripts/octelium-tunnel-check.py
```

The workflow uses the existing production AWS role to read the DNS token and
Tunnel UUID from SSM, and `CLOUDFLARE_ZONE_SETTINGS_TOKEN` to remove the old
hostname-specific origin/TLS rules. The latter needs zone read, Origin Rules
edit, and Config Settings write. API responses remain in a temporary private
log. Retry after correcting declared inputs if any stage fails; partial DNS
changes are possible and the workflow is idempotent.

The old UPnP CronJob is suspended and its Grafana lease alert paused. It no
longer renews router mappings; any prior leased mapping expires naturally.
The dedicated gateway and cluster split DNS remain available for in-cluster
clients. The legacy origin-port apply workflow now rejects use.

For rollback, revert the Tunnel configuration and pod revision through a
reviewed PR. Do not restore WAN DNS or port forwarding without a separately
reviewed transport change. Preserve private cluster access during rollout.

The workflow succeeds with an `already absent` message when no owned rule
remains. Reapply it with the default command above.

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

NOFX uses `https://nofx.stinkyboi.com` through the public Octelium `nofx` WEB
Service, which requires `homelab-human-web-access` before NOFX's own login. Its
Istio route remains private and does not expose a direct public or Tailscale
Funnel path.

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

Octelium is the primary private Service and access system for users, Cordium,
and CI.
Tailscale remains deployed as a temporary Talos/LAN/egress fallback rather
than the app, Kubernetes, callback, or GitHub Actions backbone. The `tailscale`
Argo CD Application installs the upstream
Tailscale Kubernetes Operator and applies the repo-owned `homelab-exit-node`
`Connector` from `clusters/homelab/apps/tailscale/exit-node-connector.yaml`.

The connector is cluster-scoped, creates one operator-managed proxy device, and
advertises that device as a Tailscale exit node with hostname
`homelab-exit-node` and tag `tag:k8s`. Tailnet clients can select that device as
their exit node to route internet-bound traffic through the homelab cluster
egress path. It also advertises the `10.1.0.0/24` homelab LAN route so tailnet
clients can reach local network services through the same operator-managed
device when Octelium is unavailable or when a local-LAN workflow has not yet
moved. GitHub Actions uses Octelium Service `kubernetes-api-ci` instead of this
tailnet route.

Do not remove the Tailscale Application while the operator is remote. Retire it
only after direct `octelium connect` plus `kubernetes-api.homelab`, the same
Service from a Cordium Workspace, and a replacement Talos transport have all
been validated from outside the homelab.

After the desired state syncs, verify Istio no longer owns a Tailscale device
while the fallback Connector remains:

```sh
kubectl -n istio-system get service istio-ingressgateway -o yaml
kubectl -n tailscale get statefulset,pod \
  -l tailscale.com/parent-resource=istio-ingressgateway
kubectl -n tailscale get connector homelab-exit-node
```

Expect a `ClusterIP` Istio Service with no Tailscale class or annotations, no
matching ingress proxy objects, and a ready `homelab-exit-node` Connector.

This repository cannot approve tailnet routes by itself. The tailnet policy must
allow `tag:k8s-operator` to own `tag:k8s`, and either auto-approve exit-node
and `10.1.0.0/24` route advertisement for `tag:k8s`, or rely on an admin
manually approving `homelab-exit-node` and the advertised route in the Tailscale
Machines page after sync.

Validate the exit node after Argo CD syncs Tailscale:

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get deployment,statefulset,pod
kubectl -n istio-system get service istio-ingressgateway
```

Expected result: the operator and exit-node proxy use the chart's `v1.102.3`
image, the proxy StatefulSet has matching current and update revisions, the
connector reports exit-node status and the `10.1.0.0/24` route, and the Istio
Service remains `ClusterIP` with no Tailscale address. The singleton proxy can
briefly interrupt fallback access during upgrades. Then select
`homelab-exit-node` on a client and verify DNS, HTTPS egress, and LAN access.
Keep local-network access enabled on clients that still need their nearby LAN
while using the exit node.

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
