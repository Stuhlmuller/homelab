# DNS Publication Contract

## Reviewed Kubernetes input

Only `traefik/traefik-private`, a `type: LoadBalancer` Service with `loadBalancerClass: tailscale`, may publish private application names. It must carry:

```yaml
metadata:
  labels:
    homelab.rst.io/private-dns: approved
  annotations:
    coredns.io/hostname: stinkyboi.com,affine.stinkyboi.com,...,*.cordium.stinkyboi.com
```

At initial migration, the deployed annotation holds the full 27-name inventory from the spec, not the ellipsis above. The resolver watches `resources Service` with
`serviceLabelSelectors homelab.rst.io/private-dns=approved`. A permanent CI contract check rejects missing/duplicate/out-of-zone names, mismatch with private Traefik HTTPS routers, publication of
retired names, additional selected Services, and any switch to Ingress/HTTPRoute or endpoint-resolution sources. A separate explicit first-rollout check requires exact equality with the 27-name
inventory; route-plus-annotation parity remains the continuing approval rule and accepts later reviewed names without inventory edits. Approved names map to the current
`status.loadBalancer.ingress[*].ip`; they never map to arbitrary Pod, ClusterIP, or peer IPv6 addresses.

Adding or removing a future name updates the Traefik route and Service annotation as one reviewed exposure change. The resolver controller syncs the corresponding in-memory DNS answer from the Service
watch; the operator does not edit zone records. At the first later reviewed name removal, verify the locally authoritative answer disappears. Before public-record retirement, its old public
A/AAAA/CNAME can still appear through fallthrough; the removal check distinguishes this forwarded response from a private answer, and public retirement remains a separate gate.

## Wire contract on the DNS Service

The resolver accepts DNS on UDP 53 and TCP 53 at its Tailscale-assigned IPv4. It is selected under `stinkyboi.com` only by the owner's restricted tailnet nameserver setting. It does not become a global tailnet nameserver.

| Query | Expected response while healthy |
| --- | --- |
| Each approved exact name A | One or more A answers matching published `traefik-private` IPv4; local authoritative response. |
| `<workspace>.cordium.stinkyboi.com` A | Same private A for a valid single-label workspace; `cordium.stinkyboi.com` and apex are separately declared. |
| Approved name AAAA | Expected NODATA while only the IPv4 ingress address is published; prove this with a direct runtime query before handoff. No public AAAA leakage. |
| Unapproved name A/AAAA, including unrelated public Mastodon | Forwarded public answer, or public NXDOMAIN. Never a synthetic private Traefik A. |
| Apex MX/TXT/CAA/NS/SOA and other non-address types | Forwarded public answer, retaining mail, verification and zone metadata. |
| Approved name after public record retirement with no private resolver/record | No usable address; never a public application A/AAAA/CNAME. |

The plugin TTL and cache maximum are 30 seconds. The permanent offline contract exercises paired add/change/remove declarations. At initial rollout, the repo-owned read-only check queries the observed
resolver tailnet IP over UDP and TCP, compares all 27 newly registered names with live Service status, and verifies local authority/provenance. This proves the Service watch publishes the approved
names, while future rename/removal convergence remains to be observed on the first actual reviewed change. Its explicit initial-handoff mode requires the 27-name baseline. Run it from the trusted
signer before handoff and when diagnosing or recovering an outage.

## Existing HTTP contract

DNS supplies an address only. TLS certificates, host routing, backend selection, Fleet setup denial, Harbor OCI/token paths, native API gRPC, and isolated Funnel callbacks remain owned by the existing Traefik manifests. No DNS declaration authorizes an otherwise absent HTTP route.
