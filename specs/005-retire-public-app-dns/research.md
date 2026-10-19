# Research: Retire Public App Subdomain DNS

This design narrows the public record retirement prepared by
[`004-tailnet-service-dns`](../004-tailnet-service-dns/). It uses the repository's
existing resolver and Cloudflare retirement path. Source inspection establishes
the intended behavior; live cutover evidence remains a separate gate.

## Decision 1: Derive the 26-name retirement set from the approved snapshot

**Decision:** Keep all 27 names in `scripts/config/tailscale-private-dns.json`
and the Traefik Service annotation. Select the 26 entries other than
`stinkyboi.com` only when querying, previewing, or deleting public records.
Retain the existing fixed migration-set validation so a later app addition
cannot silently expand this one-time cutover.

**Rationale:** The healthy tailnet resolver must continue answering the apex
privately. Public apex A, mail, certificate validation, and unrelated names
remain in the Cloudflare zone. The private approval set and public retirement
set now have different membership by design.

**Alternatives considered:** Removing the apex from the private annotation
would change tailnet application behavior. Deleting all 27 public names would
contradict the owner's narrowed scope. Creating a second editable hostname
catalog would risk drift from the approved snapshot.

## Decision 2: Reuse the guarded exact-record helper

**Decision:** Narrow `scripts/tailscale-private-dns.sh` and its Python
preflight to the derived 26-name set. Keep exact A/AAAA/CNAME filtering,
Cloudflare zone identity and complete-page checks, the reviewed-main SHA,
private evidence file, saved record baseline, measured prior authoritative
TTL, private resolver and HTTPS checks, readback, and idempotent partial retry.
Do not add a public record publication mode.

**Rationale:** Those existing guards already prevent a broad zone deletion and
an unreviewed live write. They need a smaller target set, not a new DNS server
or Cloudflare integration. The helper obtains its existing Cloudflare token
through the repository's SSM contract.

**Alternatives considered:** Manual Cloudflare deletion bypasses reviewed code
and drift checks. Replacing the helper or adding another provider duplicates
working safeguards. A zone-wide wildcard or bulk-delete operation can affect
unrelated public hosts.

## Decision 3: Keep private and public acceptance separate

**Decision:** Preflight all 27 normal tailnet DNS answers and canonical HTTPS
routes. Capture caller and special-path acceptance before deletion. After the
old maximum public TTL, check authoritative and recursive public DNS for no
A/AAAA/CNAME answer at every retired owner and a concrete Cordium wildcard
child. Compare preserved apex and intentionally public answers to the
pre-cutover baseline, then recheck private clients.

**Rationale:** Direct resolver health alone does not prove the owner's split
DNS setting reaches ordinary clients. An exact Cloudflare record readback does
not prove a public CNAME chain, broader wildcard, or cache no longer answers.
The apex remains public, so fail-closed acceptance applies to the 26 retired
subdomains, not to the apex.

**Alternatives considered:** Treating the Cloudflare API deletion response as
the final result omits caches and wildcard expansion. Removing unexpected
wildcards or unrelated records automatically would exceed the approved set;
the cutover must stop for a separate reviewed decision instead.

## Decision 4: Restore private DNS on failure

**Decision:** On a private resolver or signed proxy failure, recover the
repository-owned resolver, Service, or fixed Tailnet Lock signature through
the declared Argo/Terragrunt and signer paths. Do not republish retired public
app addresses as an outage response. A later policy reversal needs a separate
reviewed change.

**Rationale:** Public fallback would defeat the owner's private-only policy
for those subdomains. The resolver is stateless and already has a read-only
health checker and documented recovery path.

**Alternatives considered:** Recreating public A/AAAA/CNAME records restores
off-tailnet reachability but reverses the requested security boundary.

## Evidence and remaining live checks

- The current source has 27 approved names, including the apex, plus four
  separately retired legacy names. The guarded helper currently targets all
  27; only the 26-name target selection and dependent evidence/tests need
  narrowing. [Inventory](../../scripts/config/tailscale-private-dns.json),
  [helper](../../scripts/tailscale-private-dns.sh),
  [preflight](../../scripts/tailscale-private-dns-check.py).
- The private resolver watches the approved Traefik Service and forwards
  unrelated names and non-address types to public resolvers.
  [Resolver values](../../clusters/homelab/platform/tailnet-dns/values.yaml),
  [health checker](../../scripts/tailnet-dns-check.py).
- Traefik's wildcard certificate uses the Cloudflare DNS-01 issuer. The public
  zone and validation capability must remain.
  [Certificate](../../clusters/homelab/apps/traefik/certificate.yaml),
  [issuer](../../clusters/homelab/apps/cert-manager/issuer.yaml).
- Whether public records, broader wildcards, off-tailnet callers, and
  certificate validation are healthy at execution time cannot be established
  from repository source. Record fresh read-only evidence before executing.
- A read-only public recursive check on 2026-10-18 found an A, AAAA, or CNAME
  answer for each of the 26 target names. This is context, not the required
  Cloudflare record-ID baseline or proof of state at cutover.
