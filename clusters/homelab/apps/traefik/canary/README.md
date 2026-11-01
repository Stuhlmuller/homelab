# Dormant private-ingress canary

This directory is deliberately absent from the live Traefik Kustomization,
Helm values, and Argo Application. Rendering it changes no live traffic.
Register this directory as a separate reviewed Argo source only after the
gates below pass. Do not point the existing `traefik` Application at it.

The StatefulSet uses separate `traefik-sidecar-canary` Pod labels. Its headless
Service exposes only `/ping` on port 9000. It has no Tailscale LoadBalancer,
private-DNS approval label, Funnel, or registry Service. The existing Services
select `app.kubernetes.io/name=traefik` and cannot select this Pod. The Pod
generates its own route ConfigMap from copies of the live route sources. It
mounts the live `traefik-tls` Secret read-only, so routes and certificate match
the old controller without changing its ConfigMap. The source test requires
exact equality, so route changes must update both copies. Its private and
callback listeners bind to `127.0.0.1`; raw TCP Serve forwards only tailnet
port 443 to `127.0.0.1:8443`. Traefik still terminates TLS. The canary-scoped
Istio DENY rule rejects direct Pod-IP traffic on listener ports as a second
barrier, but acceptance must still prove that rule in ambient mode.

## Credential and state contract

Before registration, define `tag:homelab-ingress-canary` with reviewed ownership
and policy tests. Generate a dedicated, single-use, non-ephemeral Tailscale
auth key for that tag and store it in SSM SecureString
`/homelab/tailscale/traefik-sidecar-canary-auth-key` through a reviewed
repository-owned path. Declare the SSM slot and its reader IAM grant, then add
the exact key to `policy/kubernetes.rego` and `traefik` to the `aws-ssm`
ClusterSecretStore namespace allowlist in the activation PR. These grants do
not exist yet. `auth-externalsecret.yaml` is staged
but excluded from this Kustomization until those grants pass. When registered,
it projects `traefik-sidecar-canary-auth` key `auth-key` in `traefik`. Do not
reuse the operator OAuth Secret. This source contains no credential value.

`tailscaled` stores its durable identity in the Kubernetes Secret
`traefik-sidecar-canary-state`. Its Role allows namespace-wide `create` only
because Kubernetes RBAC cannot restrict Secret creation by `resourceNames`;
`get`, `update`, and `patch` are restricted to that exact name. It cannot list
or delete Secrets. The state Secret is **not** an Argo resource, so self-heal
cannot reset it. A dedicated canary ServiceAccount keeps this permission off
the live Traefik identity. The Pod disables automatic token mounting and
projects a token only into the Tailscale container. Traefik cannot read the
token, auth key, or state Secret through its own mounts.

The startup hook waits for restored state. A `Running` identity skips the auth
key; only `NeedsLogin` reads the file-backed key, so an expired enrollment key
does not break an ordinary restart. A lost or expired device identity needs a
fresh key. Tailnet Lock must sign the exact canary identity before traffic is
accepted; the current signer only covers the operator proxy.

## Activation gates

1. Run `scripts/ci/traefik-sidecar-canary-test.rb`, render this directory, and
   confirm restricted Pod Security admission, nonroot userspace Tailscale,
   Secret creation/state persistence, and both container readiness in the
   actual cluster. The published image and rootless kube store have not yet
   been exercised together.
2. Recheck `acer` memory, CPU, image-pull space, peak use, and concurrent rollout
   surge. The 2026-11-01 sampled peak left about 3,164 MiB before this canary's
   768 MiB memory limit; keep at least 512 MiB after the canary and any surge.
   Preserve a control-plane reserve and prove the image pull and admission on
   `acer` before activation.
3. Extend the exact-identity Tailnet Lock signer and provision the dedicated
   auth key. The current broad tailnet grant reaches every signed device,
   regardless of this canary tag. Narrow that grant and add a test-client rule
   before signing; prove production clients cannot reach the canary device or
   Service. Test HTTPS only. Port 80 needs a separate reviewed caller decision.
4. Prove the canary's TCP Serve config and original certificate using an
   authorized tailnet client. Probe HTTP/HTTPS by Pod IP, headless Service,
   and sidecar tailnet IP from same-node and remote-node Pods; direct private
   routes must fail even when Tailscale is absent, restarting, or unsigned.
   Add narrowly scoped backend Istio `ALLOW` rules for the distinct
   `cluster.local/ns/traefik/sa/traefik-sidecar-canary` principal before
   expecting all routes to pass; current backends allow only the live Traefik
   identity. Probe registry, Funnel, Harbor pulls, native Octelium API, and
   rollback on the still-live controller before any DNS or Service cutover.

The broader cutover and DNS identity contract are in
[`docs/runtime-isolation.md`](../../../../../docs/runtime-isolation.md).
