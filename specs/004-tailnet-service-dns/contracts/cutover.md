# Tailnet DNS and Public-Retirement Contract

This historical contract remains the 27-name private resolver and owner
handoff contract. Its original public-record retirement scope is superseded by
the [26-name app subdomain contract](../../005-retire-public-app-dns/contracts/cutover.md).
The public apex, mail and DNS-01 records, and Cloudflare zone remain.

## Handoff boundary

Before asking the owner to change tailnet DNS, record read-only evidence that the resolver's LoadBalancer Service IP matches its online, signed `homelab-dns` proxy, and that an ordinary tailnet client
can query that IP over UDP/TCP 53 for all 27 names. The owner adds **one restricted nameserver for `stinkyboi.com`** with that verified IP. If exit-node clients need the rule, enable Tailscale's
per-nameserver **Use with exit node** option. Keep global nameservers, MagicDNS, search paths and unrelated DNS rules unchanged.

The owner handoff occurs before public record deletion. The user requested a pause at this boundary; a successful direct query is not proof that normal OS resolution uses the new setting.

## Public retirement

Use the [current contract](../../005-retire-public-app-dns/contracts/cutover.md)
and [quickstart](../../005-retire-public-app-dns/quickstart.md). The reviewed
helper selects only the 26 approved non-apex subdomain owners' A/AAAA/CNAME
records. It requires a fresh baseline and exact record preview, all 27 private
answers, HTTPS and caller acceptance, per-name off-tailnet decisions, and an
effective-answer guard before the first DELETE. Wait the old maximum TTL after
the last deletion, then verify public absence for the 26 names and a concrete
Cordium child. The apex remains public and privately answered while healthy.

## Recovery and rollback

Run the repo-owned read-only DNS check from the trusted signer Mac with tailnet and read-only Kubernetes access to query the observed resolver IP over UDP and TCP, then inspect Argo health, resolver
Pods, Service status and the signed proxy peer to locate a failure. Use Argo/Terragrunt desired state to restore the resolver or its Service declaration, and re-sign only the fixed proxy identity if
Tailnet Lock rotated it. Re-run the check for all 27 answers and verify normal clients after recovery. After public retirement, do not add a public fallback for resolver faults; recovery never
restores the 26 retired subdomains' public A/AAAA/CNAME. A separate owner decision to reverse the private-DNS policy would need a new reviewed change. Never relax Traefik access restrictions or remove unrelated records.
