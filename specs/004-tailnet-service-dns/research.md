# Research: Private Tailnet Service DNS

## Decision: One stateless Kubernetes-aware DNS server

Use [k8s_gateway](https://github.com/k8s-gateway/k8s_gateway) 1.9.0 / chart 4.0.0 in its own namespace. Its Service source reads a reviewed hostname annotation and LoadBalancer status, and its
`serviceLabelSelectors` limits watches to the one private Traefik Service. The annotation overrides the synthetic `service.namespace` alias; comma-separated hosts and wildcard names are supported in
the pinned [source](https://github.com/k8s-gateway/k8s_gateway/blob/v1.9.0/kubernetes.go). The current Traefik Service has only a published IPv4; prefer that Service status IP over its MagicDNS
hostname. CoreDNS remains stateless, with no DNS database, TSIG or controller writing records.

**Alternatives considered**: BIND9 with ExternalDNS RFC2136 is documented but adds authoritative storage, update credentials and deletion reconciliation via AXFR. CoreDNS/etcd adds a state store.
Reusing cluster-internal CoreDNS couples external tailnet DNS to `cluster.local` and the current Harbor/Octelium rewrites. Direct exposure of every application Service cannot retain the existing
Traefik host/path/TLS protections.

## Decision: Split query types inside the resolver

The plugin answers approved A/AAAA records and returns NODATA for a missing address family, but it also synthesizes SOA/NS and does not preserve public mail/TXT answers for an approved apex. Use
[CoreDNS view](https://coredns.io/plugins/view/) with an A/AAAA-only first server block; a final catch-all block forwards other query types to the existing public resolver addresses `1.1.1.1` and
`1.0.0.1`. Within the first block, configure plugin `fallthrough` to [CoreDNS forward](https://coredns.io/plugins/forward/) for unmatched A/AAAA names. This preserves `mastodon.stinkyboi.com` and
other unrelated public names. Use the same explicit public upstreams as cluster CoreDNS rather than `/etc/resolv.conf`, which could loop through Kubernetes DNS.

**Limitation**: While old public A/AAAA records still exist, a missing selected Service or missing status IP can fall through to those public records. Therefore direct resolver acceptance must prove
an authoritative private answer for all 27 names before public retirement. After all selected public A/AAAA/CNAME and wildcard records are absent, a missing private answer has no public application
address to fall back to. Keep the public retirement gate strict.

**Alternative considered**: A full private authoritative zone would hide unrelated public hosts and break public apex MX/TXT/CAA. Static CoreDNS hosts would require a record edit on every service address or name change.

## Decision: Approval remains explicit on the shared ingress Service

`traefik-private` receives `coredns.io/hostname` with exactly the approved 27 names for initial migration and a private-DNS selector label. This is the reviewed private exposure declaration. The DNS
plugin watches only selected Services, never the broad Ingress source; Compass has discovery-only Ingresses that would otherwise publish names. CI validates that annotation names correspond to private
Traefik routes, checks initial baseline equality, excludes the four retired names, and expands one real Cordium wildcard sample. When a route/name changes, a reviewed Service annotation change is
deployed through the same GitOps path; DNS updates from the watch and its 30-second TTL without a DNS-record operation. The old JSON inventory is a migration/cutover baseline, not a second future
publication database.

**Alternative considered**: Generating records from all Kubernetes Services or Ingresses silently publishes unapproved names. Translating every Traefik file-provider route to another routing API solely for DNS would be a large access-path rewrite.

## Decision: Tailnet-reachable UDP and TCP DNS

The chart's LoadBalancer Service uses `loadBalancerClass: tailscale`, exposes both UDP/TCP 53, and has a fixed `homelab-dns` hostname.
[Tailscale operator ingress](https://tailscale.com/docs/kubernetes-operator/ingress) supports layer-3 TCP and UDP exposure. Reuse the operator-owned `tag:homelab-ingress`: the existing
`autogroup:member` wildcard grant already permits member traffic to port 53, so no policy mutation is needed. The DNS Service, hostname and tailnet IP remain distinct from Traefik's proxy. The current
Tailnet Lock signer must verify/sign the new operator proxy before the IP is offered. Restricted CI tags receive no new DNS grant. Two stateless resolver replicas protect the CoreDNS process, while
the single operator-managed proxy remains an availability dependency. Recovery uses Argo and the existing signing path; no PVC or backup is needed for DNS answers.

**Alternative considered**: ProxyGroup HA adds another operating dependency; the first rollout uses one resolver endpoint with a documented read-only direct-query check and recovery path. A global
tailnet nameserver would redirect unrelated domains and expand blast radius. Use [restricted split DNS](https://tailscale.com/docs/reference/dns-in-tailscale) for `stinkyboi.com`, and enable the
documented exit-node option only if those clients need it.

## Decision: Reviewed staged delivery

Argo CD 3.4 supports a [public OCI Helm chart source](https://argo-cd.readthedocs.io/en/latest/user-guide/oci/) with `path: .`; AppProject must admit its exact OCI URL. The chart is version 4.0.0,
observed OCI digest `sha256:b02209df03b08706179875b6e1887cb6064a589b591a0ce1e809a354811e37a7`. The actual container source is
`codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4`; GHCR does not publish that version. The strict image coverage/publisher path
currently lacks Codeberg. Add the Codeberg registry to its reviewed allowlist, Talos mirror map and image catalog. Add a fixed `dns` image scope and update publisher workflow/policy pins: the current
full-catalog publication fails on an unrelated LiteLLM duplicate-descriptor index. Publish and verify the exact DNS index into Harbor before the consuming Application reaches `main`. Render the chart
with a direct Harbor mirror image reference, which avoids requiring a live Talos mirror reconfiguration for this Pod.

The owner requested the handoff before changing tailnet DNS. The verified DNS Service IP is assigned by Tailscale at rollout, so it cannot be invented in source. Record that observed IP with the
restricted-domain setting after read-only inspection, then pause for the owner. The provider has a `tailscale_dns_split_nameservers` resource, but using it here would apply the change that the owner
specifically wants to perform at the handoff.

Public A/AAAA/CNAME retirement follows, never precedes, the owner's DNS setting and normal-client checks. The current Cloudflare helper already has exact-main guards and per-name readback; extend that
path for all 27 rather than introducing a second writer. Require live public baseline, old TTL, off-tailnet apex/Cordium impact acceptance, Traefik/Fleet/Harbor/native API/callback checks and post-TTL
public absence. Existing [cutover runbook](../../clusters/homelab/apps/traefik/CUTOVER.md) distinguishes ingress preflight from DNS acceptance; neither source declarations nor earlier ingress results
prove current live DNS.

## Remaining runtime evidence gates

- Current public DNS records and their maximum TTL; do not infer live state from the JSON inventory.
- Actual DNS Service IP, peer identity, signed Tailnet Lock state, UDP/TCP 53 reachability and all 27 direct private answers.
- Normal OS resolver behavior and existing HTTPS/critical client checks after the owner updates tailnet DNS.
- Off-tailnet users of the apex and Cordium wildcard before public retirement.
- Image publication receipt and live Argo/Talos pull health before resolver rollout.

These are measured rollout gates, not unresolved design choices.
