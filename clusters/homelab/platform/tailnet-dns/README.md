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
first rollout with the 27-name migration inventory. Later approved names require
one route plus annotation change in the same PR, then the Service watch updates
DNS without a record edit. A/AAAA for approved names are local; unmatched A/AAAA
and all other record types go to public resolvers. The current Traefik Service
publishes IPv4, so approved AAAA is authoritative NODATA. The TTL/cache bound is
30 seconds.

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
requires authoritative A and AAAA responses over UDP/TCP for all 27 names,
including a concrete Cordium wildcard child. It also checks public apex MX/TXT
and an unrelated public name. A successful direct query is the handoff gate;
the owner then adds this IP as a **restricted `stinkyboi.com` nameserver** in
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
requires owner DNS confirmation, all 27 private answers and HTTPS routes,
with declared and live zero-replica checks for intentionally stopped apps,
per-name off-tailnet caller decisions, a complete public baseline, and the old
maximum TTL. Preview and execute from reviewed `main`; verify public absence
for the 26 subdomains after that TTL. Preserve the Cloudflare zone, public apex
records, DNS-01 validation, the four legacy public endpoints, and unrelated
names. The initial resolver rollout stopped before owner DNS handoff and did
not delete public records.
