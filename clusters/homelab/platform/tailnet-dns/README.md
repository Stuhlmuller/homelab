# Tailnet application DNS

This separate CoreDNS/k8s_gateway resolver answers the approved
`stinkyboi.com` application names from the live `traefik/traefik-private`
LoadBalancer Service IP. Traefik still terminates HTTPS and chooses routes.
The resolver does not replace cluster `kube-dns`, store a zone database, or
publish from ordinary Services and discovery Ingresses.

The reviewed source of private names is the Traefik Service's
`coredns.io/hostname` annotation, paired with hosts in
[`routes.yaml`](../../apps/traefik/routes.yaml). The Service has the only
`homelab.rst.io/private-dns=approved` label. The permanent static check rejects
route/annotation drift; the one-time `--initial-migration` check compares the
first rollout with the reviewed migration inventory. Later approved names require
a route, the Service annotation, and the resolver's private view allowlist in
the same PR. The static check rejects drift among them. The Service watch then
updates the approved address without a DNS record edit. Approved A/AAAA queries
stay in the private view; an absent Service or empty/unready EndpointSlice cannot
fall through to public DNS. Unrelated A/AAAA and all non-address record types
use public resolvers. The current Traefik Service publishes IPv4, so approved
AAAA is authoritative NODATA. The TTL/cache bound is 30 seconds.
After endpoint withdrawal, a prior private answer can remain in resolver cache
for that bound; client caches may last longer. A sidecar cutover therefore also
needs an identity-bound traffic guard during peer loss or IP reassignment. The
live canary must deny traffic immediately after withdrawing the test peer,
while a previously returned A record is still cached.

The pinned resolver behavior can be checked without a live write. Build
`k8s_gateway` v1.9.0 from its pinned source, then run
`python3 -I scripts/ci/tailnet-dns-runtime-test.py --resolver-bin <BINARY>` in
the repository's Nix shell. The fixture renders chart 4.0.0, serves a local
Kubernetes API and public DNS stub, and checks ready, unready, empty, and
missing-Service states over UDP/TCP. It keeps public A/AAAA and apex MX/TXT
answers available while private A/AAAA never reaches the public forwarder.

The approval label is selected cluster-wide; it is controlled by reviewed
manifests and Kubernetes write access, not an admission policy. The handoff
checker fails if any live Service other than `traefik/traefik-private` has it.

The `tailnet-dns` Terragrunt Application depends on Tailscale and Traefik
registration. Wait for both upstream Applications and this resolver to be
Synced/Healthy. The Helm chart has cluster-scoped read-only RBAC for its Service
watch; its two Pods are stateless. No persistent volume, backup, or secret is
needed for DNS answers. Tailscale operator owns the proxy identity.

## Delivery and handoff

Publish and verify the pinned DNS image in Harbor before merging the consuming
Application. Follow the [render and rollout checks](../../../../specs/004-tailnet-service-dns/quickstart.md).
Apply the reviewed `tailnet-dns` stack through Terragrunt/Argo, not a direct
`kubectl` write. The Service exposes UDP and TCP 53 with the Tailscale
`homelab-dns` hostname and the existing operator-owned `tag:homelab-ingress`.
The DNS proxy has its own peer identity and IP. The trusted local signer runs
`python3 -I scripts/tailscale-ingress-sign.py --dns-only` for preview and
`--dns-only --execute` for
the exact fixed proxy identities. Record the Service's **observed** tailnet
IPv4 and signed peer privately; do not use the Traefik ingress IP as the DNS
server address.

From the trusted signer Mac with tailnet access and read-only cluster access, run:

```sh
python3 -I scripts/tailnet-dns-check.py --server <DNS_TAILNET_IP> --initial-handoff
```

It binds the supplied IP to the online signed proxy and live Service, then
requires authoritative A and AAAA responses over UDP/TCP for all reviewed
private names, including a concrete Cordium wildcard child. It also checks
public apex MX/TXT and an unrelated public name. A successful direct query is
the handoff gate. The owner then adds this IP as a **restricted `stinkyboi.com`
nameserver** in
Tailscale DNS. Enable **Use with exit node** for that nameserver if the clients
use an exit node. Leave unrelated tailnet DNS settings alone. Normal OS lookup
and HTTPS acceptance follow the owner change, before public record retirement.

## Recovery and later public retirement

For an outage, run the same checker without `--initial-handoff`, inspect Argo,
Pods, Service status and the proxy's Tailnet Lock signature. Restore the failed
declaration through reviewed Argo/Terragrunt desired state; if only its key
rotated, use the fixed signer. Re-run direct UDP/TCP and normal client checks.
After public app subdomain retirement, the 26 retired non-apex names fail
closed while the resolver is down; do not restore public app A/AAAA/CNAME as
an outage workaround. The apex remains privately answered while healthy and
retains its existing public A and mail records.

The current [26-name cutover contract](../../../../specs/005-retire-public-app-dns/contracts/cutover.md)
requires owner DNS confirmation, all reviewed private answers and HTTPS routes,
with declared and live zero-replica checks for intentionally stopped apps,
per-name off-tailnet caller decisions, a complete public baseline, and the old
maximum TTL. Preview and execute from reviewed `main`; verify public absence
for the 26 subdomains after that TTL. Preserve the Cloudflare zone, public apex
records, DNS-01 validation, the four legacy public endpoints, and unrelated
names. The initial resolver rollout stopped before owner DNS handoff and did
not delete public records.
