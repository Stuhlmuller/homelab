# Specify input: Private tailnet DNS answers

Use this feature description with `$speckit-specify`. The [decision](decision.md) is a go to specification for Concept Option B; [research](research.md) contains source evidence. No implementation or live cutover has been authorized by this assessment.

> Specify private DNS answers for all 27 currently declared `stinkyboi.com` Kubernetes application names, including the apex and Cordium wildcard, on ordinary tailnet clients. Approved names must
> register automatically as reviewed Kubernetes exposure declarations change. Retain Traefik as the HTTPS and path-routing owner and preserve existing application URLs and access restrictions. After
> verified private cutover and cache expiry, remove public A/AAAA/CNAME answers for those 27 names; preserve public answers for unrelated names such as the planned Mastodon host. Private names must
> fail closed if the resolver is unavailable. Only reviewed service names may become tailnet-visible. All desired state, including tailnet DNS settings and record retirement, must have a
> repository-owned declarative path. Define client-visible success, outage recovery, migration checks, public-caller impact, and rollback without assuming the repository's declared DNS cutover is
> already live.

## Owner decisions

- Private DNS answers are the priority; keeping Traefik is acceptable if registration is automatic.
- All 27 current inventory entries move, including `stinkyboi.com` and `*.cordium.stinkyboi.com`.
- Public records for those 27 names are removed after cutover; resolver failure means private names fail closed.

## Questions for specification

- Which reviewed Kubernetes declarations authorize future names, and how are unapproved Services excluded?
- How will tailnet clients still resolve unrelated public `stinkyboi.com` names, including Mastodon, while the 27 private names have no public answers?
- Which off-tailnet clients still rely on the apex or Cordium wildcard, and what accepted migration or loss of access follows from removing their public records?
- What recovery target, resolver redundancy, and reviewed rollback path meet the confirmed fail-closed behavior?

## Evidence to carry forward

- `scripts/config/tailscale-private-dns.json` declares 27 names; `clusters/homelab/apps/traefik/routes.yaml` declares 28 routers. Neither count proves current live DNS state.
- `clusters/homelab/apps/compass/ingress-discovery.yaml` is catalog discovery, not an application traffic route. Do not treat every Ingress as an approved private DNS source.
- `IaC/modules/tailscale-access/main.tf` declares tailnet policy and identity, but no current repository-owned nameserver setting was found. The specification needs a declarative ownership boundary for that desired state.
- `clusters/homelab/apps/traefik/CUTOVER.md` distinguishes ingress preflight from DNS cutover and includes client HTTPS, Fleet, Harbor node pulls, native API, and public callback checks. `clusters/homelab/apps/octelium-public/configmap.yaml` still declares public routes for the apex and Cordium wildcard; their off-tailnet use needs explicit acceptance before DNS retirement.
- [Tailscale split DNS](https://tailscale.com/docs/reference/dns-in-tailscale) sends matching suffix queries to a restricted resolver; the docs do not promise fallback to public DNS for missing names. [ExternalDNS Service source](https://kubernetes-sigs.github.io/external-dns/v0.21.0/docs/sources/service/) needs an approved hostname source and a tailnet-reachable target.
