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
accepted. After the policy denies every client to the canary and the Pod passes
admission, run `python3 -I scripts/tailscale-ingress-sign.py --canary-only` to
preview. Add `--execute` only from clean, signed current `main`. This separate
path requires the current ready StatefulSet revision and Pod on `acer`, its
persistent state Secret UID, pinned images, canary tag, exact node key and
local signer peer, and raw TCP 443 Serve to the Traefik loopback TLS listener.
Execution reads the applied tailnet policy through the separate private
Terragrunt OAuth client and requires it to match committed source with only
the ten reviewed legacy destination selectors. The current wildcard policy
fails this gate. No token or policy content is printed.
It accepts only the pre-Service Serve configuration; a later TailVIP Service
configuration needs a reviewed signer update before identity recovery. It
checks the TLS Secret mount, not the certificate bytes. Verify the certificate
and private route from an authorized tailnet client after signing and a separate
reviewed test-client grant.

## Exact Service host approval

After a reviewed `svc:homelab-private-ingress` definition and one test-client
TCP 443 grant are merged, run the repo-owned approval command in preview mode:

```sh
python3 -I scripts/tailscale-service-host-approve.py \
  --api-key-file ~/.config/homelab/tailscale/service-approval-api-key
```

Use an Owner/Admin API key kept outside the repository as a regular mode 0600
file in a mode 0700 directory. The command does not print it. Preview prints a
fingerprint of the observed policy, TailVIP, StatefulSet/Pod/state Secret UIDs,
device ID/public node key, Tailnet Lock signer key, and Tailscale IPs. Review
that identity and the pending advertisement. From signed, current `main` only,
the same command can take `--execute --expect-fingerprint <preview-sha256>`.
It rechecks source versus live policy, the scoped grant, exact Service ports,
converged StatefulSet/Pod revision, placement, pinned images, loopback
listeners, read-only TLS mount, signed daemon/device identity, raw TCP Serve
target, and the single pending host before one approval API write. It refuses
an auto-approved host or changed identity. An already manually approved host
gets readback only. This command does not create the Service, key, Pod,
policy grant, or Tailnet Lock signature.

Approval alone does not prove service traffic. A reported Tailscale daemon
cache issue can require a declared re-advertisement after approval; do not
cut over DNS until an authorized client reaches the TailVIP and withdrawal
and wrong-host probes fail. The [official Go client](https://github.com/tailscale/tailscale-client-go-v2/blob/main/services.go)
reads the Service definition at `/vip-services/{name}`, while the
[published API operation](https://tailscale.com/api#tag/services/GET/tailnet/%7Btailnet%7D/services/%7BserviceName%7D)
currently documents `/services/{name}`. This helper uses the client path. The
[Tailscale host-list API](https://tailscale.com/api#tag/services/GET/tailnet/%7Btailnet%7D/services/%7BserviceName%7D/devices)
uses `stableNodeID` and `not-approved`; its [approval API](https://tailscale.com/api#tag/services/POST/tailnet/%7Btailnet%7D/services/%7BserviceName%7D/device/%7BdeviceId%7D/approved)
uses the singular `device` path. The first real preview must confirm the
definition read, both host responses, and pending host before any execution.
See the [approval refresh
report](https://github.com/tailscale/tailscale/issues/18821).

For rollback, first revert any later DNS/client grant through their reviewed
GitOps or Terragrunt source and verify the old ingress still serves clients.
Remove the canary's Service advertisement through a reviewed Argo source change;
verify the TailVIP no longer reaches it. Keep the old ingress active. The
manual approval record may remain after the host stops advertising, but it
cannot route traffic without an advertisement and grant. Retire that record
only through a separate reviewed repository-owned revocation path.

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
3. Provision the dedicated auth key. The current broad tailnet grant reaches
   every signed device, regardless of this canary tag. Narrow that grant,
   prove the applied policy matches source and denies all canary destinations,
   then use the exact-identity signer. Add a reviewed test-client grant only
   after signing and before traffic probes. Prove production clients cannot
   reach the canary device or Service. Test HTTPS only. Port 80 needs a
   separate reviewed caller decision.
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
