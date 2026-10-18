# Tailnet DNS and Public-Retirement Contract

## Handoff boundary

Before asking the owner to change tailnet DNS, record read-only evidence that the resolver's LoadBalancer Service IP matches its online, signed `homelab-dns` proxy, and that an ordinary tailnet client
can query that IP over UDP/TCP 53 for all 27 names. The owner adds **one restricted nameserver for `stinkyboi.com`** with that verified IP. If exit-node clients need the rule, enable Tailscale's
per-nameserver **Use with exit node** option. Keep global nameservers, MagicDNS, search paths and unrelated DNS rules unchanged.

The owner handoff occurs before public record deletion. The user requested a pause at this boundary; a successful direct query is not proof that normal OS resolution uses the new setting.

## Retirement preconditions

The reviewed Cloudflare retirement path may delete only A/AAAA/CNAME records whose exact names are in the 27-name migration baseline, including the wildcard record itself. It must refuse execution until the operator records:

1. The merged reviewed-main revision, current live public baseline and largest existing TTL, plus a dry-run list of exact record IDs/types/names to change.
2. Owner confirmation that restricted tailnet DNS is active; normal OS lookups for every approved exact host and a concrete Cordium wildcard child give the intended private A. Public-only and apex non-address records still work.
3. HTTPS and access acceptance: representative apps, Fleet setup denial/check-in, Harbor uncached pulls from every Talos node, native API/gRPC and Cordium reconnect, and the restricted public callback paths.
4. Off-tailnet caller impact for `stinkyboi.com` and `*.cordium.stinkyboi.com` has been migrated or explicitly accepted.

Deletion and readback run through the existing exact-main, idempotent repository helper. It must reject any record outside the target set and preserve unrelated public names/types. Wait at least the
captured old maximum TTL after the last write; then query public authoritative/recursive DNS for A, AAAA and CNAME absence for all 27, including a concrete wildcard child, and recheck normal tailnet
client access. A failed or partial deletion is re-read and resumed from the reviewed code path; do not use ad hoc Cloudflare changes.

The prior helper's publication mode must not silently recreate those A/AAAA records after retirement. The reviewed retirement change disables that writer for the retired set. Restoration of public application records would reverse the owner's private-DNS policy and is outside this feature.

## Recovery and rollback

Run the repo-owned read-only DNS check from the trusted signer Mac with tailnet and read-only Kubernetes access to query the observed resolver IP over UDP and TCP, then inspect Argo health, resolver
Pods, Service status and the signed proxy peer to locate a failure. Use Argo/Terragrunt desired state to restore the resolver or its Service declaration, and re-sign only the fixed proxy identity if
Tailnet Lock rotated it. Re-run the check for all 27 answers and verify normal clients after recovery. After public retirement, do not add a public fallback for resolver faults; rollback never
restores public A/AAAA/CNAME. A separate owner decision to reverse the private-DNS policy would need a new reviewed change. Never relax Traefik access restrictions or remove unrelated records.
