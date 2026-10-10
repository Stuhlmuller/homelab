# Traefik mesh ingress

Traefik routes the existing private `*.stinkyboi.com` application URLs from the
Tailscale mesh directly to Kubernetes Services. Fleet remains private, including
agent enrollment and MDM. Octelium remains behind private routes for Cordium and
its required portal, API, and console. Prometheus has no external route.

The retained Octelium console passes through the existing Istio TLS gateway.
Its [conditional response filter](../octelium-cluster/console-redirect.yaml)
repairs Octelium's login return URL from `console.octelium.stinkyboi.com` to
`console.stinkyboi.com`. The upstream TLS transport verifies the console hostname;
do not remove this exception until the native console URL is corrected and login
is verified. Application routes use their Services directly.

[`routes.yaml`](routes.yaml) is the explicit host/backend inventory. The
file provider does not discover or publish arbitrary Kubernetes Services.
[`values.yaml`](values.yaml) owns four separate listeners:

| Entry point | Pod port | Source | Routes |
| --- | --- | --- | --- |
| `web` | 8000 | Private Tailscale LoadBalancer | Redirect to HTTPS port 443 |
| `websecure` | 8443 | Private Tailscale LoadBalancer | Application and Cordium/control hosts |
| `funnel` | 8080 | Two Tailscale Ingress proxies | Only the callbacks below |
| `registry` | 9443 | Declared Talos node addresses | Only Harbor OCI and token endpoints |

The `traefik-registry` ClusterIP Service reserves `10.96.0.50:443` for Talos
image pulls. Host-only resolution sends `harbor.stinkyboi.com` there on the
nodes; TLS still validates that hostname. Its router permits only `/v2`,
`/v2/` descendants, and `/service/token`, preserving Authorization headers.
Harbor dashboards, management APIs, and every other application host are excluded.
The ambient AuthorizationPolicy restricts the registry listener to the declared
node source addresses; local-node traffic also follows Istio's trusted probe
bypass. Validate containerd pulls from each node before changing DNS.

The private Service is `traefik-private`; its Tailscale hostname is
`homelab-ingress`. Public callbacks terminate TLS at their Tailscale proxies and
forward HTTP to the separate `traefik-funnel` Service. Funnel only supports
tailnet DNS names; private custom application hostnames retain the certificate
from [`certificate.yaml`](certificate.yaml).
[Tailscale Funnel documentation](https://tailscale.com/kb/1223/funnel).

| Public callback | Allowed paths | Application authentication |
| --- | --- | --- |
| `n8n-webhook.tail67beb.ts.net` | `/webhook`, `/webhook-test`, `/webhook-waiting`, and their slash-separated descendants | Workflow-specific webhook credentials/signatures |
| `policy-bot-hook.tail67beb.ts.net` | Exactly `/api/github/hook` | GitHub webhook HMAC |

All other paths on the callback hosts return 404. Supplying a private application
Host header to the Funnel listener cannot select a private router. No Fleet
router binds to the Funnel listener. Fleet's private router excludes `/setup`,
`/api/setup`, and `/api/v1/setup`, including their descendants; unmatched routes
produce Traefik's normal 404. This preserves the first-admin bootstrap boundary
even after restoring an empty database.
[Traefik rules](https://doc.traefik.io/traefik/reference/routing-configuration/http/routing/rules-and-priority/),
[unmatched-route behavior](https://doc.traefik.io/traefik/getting-started/faq/#404-not-found).

Fleet, both callbacks, and the registry listener reject ambiguous encoded reserved path
characters. Without that middleware, `/api%2fv1%2fsetup` bypasses Traefik's path
matcher before a backend decodes it. Normalized dot segments and duplicate
slashes remain subject to the route exclusions.
[Encoded-character filtering](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/encodedcharacters/).

## Mesh and certificates

Traefik joins Istio ambient so backend policies can authenticate
`cluster.local/ns/traefik/sa/traefik`. App policies permit that identity on their
existing application ports. The Traefik
[`AuthorizationPolicy`](authorizationpolicy.yaml) rejects unrelated authenticated
mesh callers and restricts registry traffic by source IP. The current Flannel
deployment does **not** enforce Kubernetes NetworkPolicy; the
[`NetworkPolicy`](networkpolicy.yaml) records intended Tailscale, Harbor signer,
and node ingress restrictions for a future enforcing CNI. External private access
depends on Tailscale ACLs and the absence of a public/LAN application listener.
Plaintext callers already inside the cluster can reach the private proxy; the
declarative namespace/pod selectors do not currently prevent that path. Harbor currently
uses an unmeshed namespace and shared `harbor` ServiceAccount. If it joins ambient,
give its signing job a dedicated identity before allowing it into Traefik.
Allowing HBONE port 15008 alone does not identify an authorized application
caller. Istio's `ipBlocks` matches packet source addresses and is supported by
ztunnel; trusted local-node probe traffic bypasses normal policy enforcement.
[Ambient L4 policy](https://istio.io/latest/docs/ambient/usage/l4-policy/),
[Istio ambient and NetworkPolicy](https://istio.io/latest/docs/ambient/usage/networkpolicy/).

The certificate covers the apex, `*.stinkyboi.com`, and
`*.cordium.stinkyboi.com`. ConfigMap and Secret files share one watched projected
directory. Kubernetes swaps its `..data` symlink on updates; watching the directory
lets the file provider reload certificate changes. Do not replace the projection
with a `subPath` mount. A plain update to an unwatched certificate file does not
reload Traefik.
[File-provider watching](https://doc.traefik.io/traefik/providers/file/),
[certificate reload behavior](https://doc.traefik.io/traefik/getting-started/faq/#why-is-my-tls-certificate-not-reloaded-when-its-contents-change).

Octelium's private API uses `h2c` to its ingress dataplane, preserving native
HTTP/2 gRPC. Cordium, Multica, and OpenClaw retain WebSocket upgrades through
their HTTP Services. Harbor receives the original Authorization header and
continues to authenticate registry clients itself.

## Validation and cutover

Run the inventory and boundary checks:

```sh
nix develop --command python3 -I scripts/ci/traefik-routes-test.py
nix develop --command kustomize build clusters/homelab/apps/traefik
```

With the declared Traefik binary installed or separately checksum-verified,
exercise the real proxy without touching Kubernetes:

```sh
nix develop --command python3 -I scripts/ci/traefik-runtime-check.py \
  --binary /absolute/path/to/traefik
```

The runtime check uses Python, Node's built-in HTTP/HTTP2 servers, `yq`, `curl`,
and OpenSSL. It downloads nothing, binds only loopback ephemeral ports, generates
temporary test certificates, and removes its processes and files on exit. It
tests all private backends, h2c, WebSocket upgrades, callback isolation, Host
spoofing, encoded/normalized paths, Fleet setup denial, registry path/header
boundaries, and projected-directory
certificate rotation. Failures print the local proxy log.

These are local checks, not deployed acceptance. Before retiring the old ingress,
verify the merged revision, Argo sync/health, certificate readiness, all private
application URLs from a mesh client, Fleet device check-in, Harbor image pulls,
and native Cordium execution/reconnection. Verify callback root/admin paths fail
from outside the mesh and signed GitHub/n8n deliveries succeed. Prove certificate
reload on the actual Linux deployment as a separate operational check.

Existing Istio routes and their access allowances remain during staged migration.
Change public callback settings and external callers only after the new Funnel
paths pass acceptance; retire the Cloudflare tunnel and non-Cordium Octelium
catalog after the remaining callers and CI transport have moved. Roll back through
a reviewed revert and the repository-owned DNS/access workflow; do not mutate
live routing objects manually. Traefik holds no persistent application data.
