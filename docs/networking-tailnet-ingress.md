# Tailnet Ingress

Octelium is the primary access plane for homelab apps, VPN sessions, CI
Kubernetes API reachability, and external callback paths. Existing
`*.stinkyboi.com` app hostnames resolve through the repo-owned
`octelium-public` Cloudflare Tunnel connector; the Octelium CLI API uses the
separate direct gRPC origin documented below. Octelium `WEB` Services normally
enforce clientless browser login before proxying to the existing private Istio
routes. AFFiNE and NOFX are anonymous at Octelium and use their own
authentication. AFFiNE's stock native client can therefore connect. Tailscale
Funnel is not an approved external-service backbone in steady state.

## DNS Model

Exact app, callback, and browser control-plane records such as
`grafana.stinkyboi.com`, `n8n-webhook.stinkyboi.com`,
`policy-bot-hook.stinkyboi.com`, and `portal.stinkyboi.com` must be proxied
CNAMEs to the `homelab-octelium-public` Cloudflare Tunnel target,
`<tunnel-uuid>.cfargotunnel.com`. Public DNS answers should be Cloudflare
anycast addresses, not Octelium private service IPs or the old tailnet
LoadBalancer IP.

`octelium-api.stinkyboi.com` is the exception. Cloudflare Tunnel public
hostnames do not support the long-running gRPC stream used by
`octelium connect`, so this name is a proxied A record to the current WAN IPv4
address. `scripts/octelium-public-dns.sh`, run from the homelab LAN, discovers
that address through UPnP, verifies the leased mapping maintained by the
`octelium-api-upnp` CronJob to the dedicated `octelium-api-ingressgateway`
NodePort at `10.1.0.200:30443`, verifies the origin gRPC response, and
reconciles the record. The dedicated gateway accepts Cloudflare origin TLS
without SNI, but a separate `VirtualService` routes only
`octelium-api.stinkyboi.com`; browser, app, and callback hostnames remain
unavailable through the WAN mapping.
See Cloudflare's
[gRPC limitation](https://developers.cloudflare.com/network/grpc-connections/#limitations)
for the public-hostname restriction.

Inside Kubernetes, `platform-dns` rewrites the same API hostname to the
dedicated `octelium-api-ingressgateway` Service. Clients keep the original
hostname for TLS and SNI while bypassing the WAN mapping and hairpin NAT. This
split-horizon route is cluster-only; public DNS remains unchanged.

The public tunnel forwards app UI hostnames to the Octelium public ingress
dataplane so Octelium can select the matching `WEB` Service and apply its
declared clientless or anonymous access mode.
The tunnel forwards the Octelium Cluster and portal browser hostnames,
Enterprise console, and unauthenticated callback hostnames to the in-cluster
Istio gateway, where explicit `VirtualService` objects keep backend routing
narrow.

Cloudflare edge TLS and the origin certificate must cover the apex plus
first-level `*.stinkyboi.com` names. That free Cloudflare certificate shape is
why `stinkyboi.com` is the Octelium cluster domain even though
`octelium.stinkyboi.com` remains a public alias.

## Route Inventory

| Surface | HTTPS host | Backbone |
| --- | --- | --- |
| Octelium browser control plane | `https://stinkyboi.com`, `https://octelium.stinkyboi.com`, `https://portal.stinkyboi.com` | `octelium-public` Cloudflare Tunnel to Istio/Octelium |
| Octelium CLI API | `https://octelium-api.stinkyboi.com` | Cloudflare normal gRPC proxy on client TCP/443, Origin Rule to WAN TCP/8443, then UPnP to the API-only Istio gateway NodePort |
| app UIs | existing `https://*.stinkyboi.com` app hostnames | `octelium-public` Cloudflare Tunnel to Octelium `WEB` Services; clientless except AFFiNE and NOFX |
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

The primary `istio-ingressgateway` Service is `ClusterIP` only and has no
Tailscale LoadBalancer. Octelium service proxies and `octelium-public` reach it
through cluster DNS, so app routes cannot bypass Octelium through a tailnet
device. The existing `tailnet-gateway` object keeps its legacy name but is only
an internal Istio TLS-routing resource. A separate gateway-chart release and
`octelium-api-gateway` TLS configuration expose fixed NodePort `30443`. Its
workload selector and API-only `VirtualService` are separate from
`tailnet-gateway`, preventing another app hostname from using the WAN listener.
The router mapping exposes only public TCP/8443 and targets worker
`zimaboard-0` at `10.1.0.200`; no public HTTP or status NodePort is declared.
The host-networked CronJob must run on that worker because the Xfinity UPnP
implementation rejects mappings submitted by a different LAN client. It
refreshes the Xfinity gateway's minimum 86,400-second lease every five minutes,
so reverting or suspending the CronJob closes the WAN listener within 24 hours.
Requests still terminate at the Octelium API and require Octelium
authentication.
If the mapping exists but WAN connections time out, use Xfinity Advanced
Security's device-specific **Allow Access** flow for `zimaboard-0`; Xfinity
[documents](https://www.xfinity.com/support/articles/xfi-port-forwarding)
that Advanced Security can block all inbound traffic to a forwarded device.
Cloudflare rules must match
`http.host eq "octelium-api.stinkyboi.com"` and override the destination port
to `8443` while setting SSL to Full (strict); the client URL remains standard
HTTPS on port `443`. Reconcile them without exposing the token by running the
protected workflow:

```sh
gh workflow run octelium-cloudflare-origin-port.yml --ref main
```

The `homelab-production` environment secret
`CLOUDFLARE_ZONE_SETTINGS_TOKEN` must grant zone read, Zone Settings read,
Origin Rules edit, and Config Settings write for `stinkyboi.com`. Zone Settings
read authorizes the workflow's SSL and HTTP/2-to-origin checks.
Rollback is the same protected path and is safe to repeat:

```sh
gh workflow run octelium-cloudflare-origin-port-remove.yml --ref main
```

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

NOFX uses `https://nofx.stinkyboi.com` through the public, anonymous Octelium
`nofx` WEB Service and owns its login boundary. Its Istio route remains private
and does not expose a direct public or Tailscale Funnel path.

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
moved. GitHub Actions uses Octelium Service `kubernetes-api-ci` instead of this
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
kubectl -n tailscale get deployment,statefulset,pod
kubectl -n istio-system get service istio-ingressgateway
```

Expected result: the operator and both managed proxy Pods use the chart's
`v1.102.3` image, each StatefulSet has matching current and update revisions,
the connector reports exit-node status and the `10.1.0.0/24` route, and the
Istio Service retains its Tailscale address. The singleton proxies roll
separately during upgrades, so brief interruptions are expected. Then select
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
