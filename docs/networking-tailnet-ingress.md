# Tailscale And Traefik Ingress

Application URLs keep their `*.stinkyboi.com` hostnames and move to private
Traefik ingress on Tailscale. Fleet devices must join the mesh. Only n8n
webhooks and Policy Bot's GitHub callback use Funnel. Cordium retains its
Octelium control plane behind private Traefik routes.

The [ordered cutover](../clusters/homelab/apps/traefik/CUTOVER.md) separates
prerequisites before DNS from CI/native transport afterward. Foundation proxies,
TLS, and the provider-owned tailnet policy must pass live acceptance first.
Phase 2a switches internal CoreDNS, additive access policies, and n8n's advertised
Funnel URL, then removes the old public DNS writer and restoration workflow.
Phase 2b switches CI and shared native operator transport only after canonical
DNS/API acceptance. Old native catalog resources, credentials, callback names,
and the Tunnel Deployment remain until the final retirement gate.

## DNS Model

`scripts/tailscale-private-dns.sh` owns a fixed inventory of DNS-only A/AAAA
records derived from the verified `traefik-private` Service and unique online
`homelab-ingress.tail67beb.ts.net` peer. It never creates CNAMEs to MagicDNS:
public recursive resolvers cannot resolve tailnet-only peer names. It preserves
unrelated records and old CI, callback, and carrier hostnames. Application DNS
can be publicly resolvable while its Tailscale addresses remain mesh-only.

```sh
python3 -I scripts/tailscale-private-dns-check.py --check
scripts/tailscale-private-dns.sh --dry-run
```

The exact-main execute command, old-TTL wait, Mac migration, and normal OS DNS
verification are separate steps in the cutover guide. An API readback alone does
not prove client access. Never run the removed public DNS writer or historical
restoration workflow after this migration.

Inside Kubernetes, `platform-dns` rewrites `octelium-api.stinkyboi.com` and
`harbor.stinkyboi.com` to `traefik-private.traefik.svc.cluster.local`. Clients
retain their original TLS hostname and SNI. Talos node image pulls use the
separate host-only `10.96.0.50` registry Service; verify pulls on every node
before changing Harbor's global DNS.

## Route Inventory

| Surface | HTTPS host | Backbone |
| --- | --- | --- |
| Application UIs, including Fleet | Existing `*.stinkyboi.com` application names | Tailscale private Traefik listener to Kubernetes Services |
| Octelium control plane for Cordium | Apex, `octelium`, `portal`, `console`, and `octelium-api` names | Private Traefik routes; native API uses HTTP/2 gRPC |
| Cordium workspaces | `*.cordium.stinkyboi.com` | Private Traefik to retained Cordium/Octelium Services |
| Kubernetes for Cordium | Private `kubernetes-api.homelab` Service | Existing restricted Octelium client session |
| CI Kubernetes after phase 2b | `homelab-tailscale-operator.tail67beb.ts.net` | Authenticated operator API proxy with scoped CI tags and Kubernetes RBAC |
| n8n webhooks | `n8n-webhook.tail67beb.ts.net` | Funnel to Traefik's separate callback listener |
| Policy Bot webhook | `policy-bot-hook.tail67beb.ts.net` | Funnel to Traefik's separate callback listener |

[`routes.yaml`](../clusters/homelab/apps/traefik/routes.yaml) is the explicit
host/backend source. The file provider does not discover arbitrary Services.
Traefik's certificate covers the apex, `*.stinkyboi.com`, and the Cordium
workspace wildcard. Application authentication remains at each backend;
Tailscale limits network access. AFFiNE native login and Harbor OCI credentials
continue to reach the application unchanged. Prometheus has no ingress.

The shared Istio gateway and old app VirtualServices remain during cutover.
Traefik uses application Services directly, except for the retained console
redirect compatibility route. See the [Traefik route boundaries](../clusters/homelab/apps/traefik/README.md).
Compass keeps its existing launch hostnames and discovery-only Ingress entries;
those names resolve to private Traefik after DNS cutover. Changing its catalog
is separate from this transport change.

## Tailnet Exit Node And LAN Route

The `tailscale` Argo CD Application owns the operator and
`homelab-exit-node` Connector. It advertises `10.1.0.0/24` and exit-node routing
with `tag:k8s`. Keep it for remote Talos/LAN access. The provider-owned complete
policy in `scripts/config/tailscale-policy.json` owns approvals and tag grants;
use the [Tailscale operator unit](../IaC/modules/tailscale-access/README.md) for
reviewed policy changes instead of editing the admin console.

```sh
kubectl get connector homelab-exit-node
kubectl wait connector homelab-exit-node --for=condition=ConnectorReady=true --timeout=5m
kubectl -n tailscale get deployment,statefulset,pod
```

The Connector must be ready and advertise the declared subnet. Verify LAN
reachability and HTTPS egress from a connected client. The Istio gateway remains
ClusterIP; Traefik owns the private application Tailscale LoadBalancer.

## Policy Bot Webhook Callback

The public Funnel route permits exactly `/api/github/hook` on
`policy-bot-hook.tail67beb.ts.net`. Policy Bot verifies GitHub's webhook HMAC
using its existing secret contract. Its UI, OAuth callback, details, and assets
stay at the private `policy-bot.stinkyboi.com` application host. Callback root
and admin requests must fail from outside the mesh.

After independent Funnel acceptance, use `scripts/policy-bot-webhook.py` to
preview and migrate the existing GitHub App webhook. Preserve its secret and
save the cutover receipt; require a fresh naturally occurring successful signed
delivery. Keep the old callback route until that check passes.

## n8n Webhook Callback

The public Funnel route permits `/webhook`, `/webhook-test`, `/webhook-waiting`,
and their slash-separated descendants on `n8n-webhook.tail67beb.ts.net`.
Authentication or signing remains workflow-specific. The editor, REST API,
assets, and root stay at private `n8n.stinkyboi.com`.

Phase 2a sets `WEBHOOK_URL` to `https://n8n-webhook.tail67beb.ts.net/` only after
Funnel readiness; n8n can re-register hooks during startup. Then migrate the two
fixed repository hooks with `scripts/n8n-github-webhooks.py`. Follow its receipt
and fresh-delivery checks; retain the old callback routes until acceptance.

## Fleet And Future Public Routes

Fleet is private, including device enrollment and MDM. Devices need Tailscale
connectivity. Fleet still authenticates users and devices; Traefik denies the
first-admin setup endpoints, and the existing internal bootstrap Job owns the
first account. Validate device check-in after DNS convergence.

Future public routes require a reviewed callback purpose, exact paths,
authentication/signature contract, exposed-data assessment, and rollback path.
They must use the isolated Funnel listener; application Host headers cannot
select private routers there. No Fleet route binds to Funnel.

## Harbor OCI clients

Private `harbor.stinkyboi.com` routes directly through Traefik to Harbor.
Authorization headers pass unchanged; Harbor enforces registry credentials and
keeps self-registration disabled. Internal Pod DNS reaches `traefik-private`;
Talos pulls use the restricted registry listener. Phase 2b moves hosted image
publication to the Tailscale operator API proxy and a reviewed TLS port-forward
to `traefik-private`. Publish and verify required images before routing changes.

## Acceptance And Rollback

Require all private app checks, Fleet check-in, per-node Harbor pulls, native
Cordium execution/reconnection, CI admission-denial checks, and fresh callback
deliveries before final retirement. Retain Octelium/Cordium persistent state,
legacy catalog credentials, the Tunnel Deployment, and owned local carrier
backups until then. Roll back only through reviewed repository desired state
and the retained carrier installer. Do not restore stale desktop credentials.
