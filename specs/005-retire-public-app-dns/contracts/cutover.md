# Cutover Contract: Retire Public App Subdomains

## Scope and interface

The repository-owned interface remains:

```text
scripts/tailscale-private-dns.sh --retire-private --dry-run [--baseline-out PRIVATE_FILE]
scripts/tailscale-private-dns.sh --retire-private --execute --expected-sha REVIEWED_MAIN_SHA --evidence PRIVATE_FILE
```

`--dry-run` may read Cloudflare and authoritative DNS but cannot write records.
`--execute` may delete only A, AAAA, or CNAME records whose exact owner is one
of the 26 approved non-apex names in the fixed migration snapshot. The apex
`stinkyboi.com` remains in the fixed first 27 migration names and the current
29-name private resolver approval but is never selected for public deletion.
The two later Enterprise names are also excluded. The helper has no publication or restoration
mode. Its private evidence file must be outside the repository.

## Required pre-write evidence

1. A clean, merged and reviewed `main` revision matches `--expected-sha`, and
   the helper, preflight, and inventory exist in that revision.
2. The observed DNS Service tailnet IPv4 belongs to the online signed
   `homelab-dns` peer. The owner has enabled the restricted `stinkyboi.com`
   nameserver. Ordinary client OS lookups resolve all 29 current approved names to
   private Traefik, including the apex and a Cordium wildcard child; direct
   UDP/TCP resolver answers and the original 27 migration HTTPS routes pass.
   The staged Enterprise backends have separate readiness. A backend
   error for an intentionally stopped app is accepted only when reviewed source
   and the live Deployment both specify zero replicas.
3. Fleet setup denial and device check-in, uncached Harbor pulls on every
   Talos node, native API, Cordium reconnect, and restricted public callbacks
   pass their documented checks. The unused Codex Review Helper GitHub hook
   `589400612` and its callback path are absent after reviewed retirement;
   surviving Github Emergency Bot and Policy Bot hooks have fresh successful
   deliveries. `off_tailnet` records `migrated` or
   `accepted_loss` for each of the 26 names, including the Cordium wildcard,
   after reviewing known callers that bypass ordinary tailnet DNS.
4. The preview has matched the selected Cloudflare API zone's nameservers to
   live public delegation and read every exact 26-name owner from that zone
   with complete pages, saved exact target record IDs and
   fields, and measured the largest old authoritative TTL. The operator has
   reviewed the proposed deletion list and preserved public apex and
   unrelated-name answers.
5. Before deletion, read the complete paginated public-zone
   wildcard/CNAME/NS inventory. Block before the first DELETE on any
   out-of-set covering wildcard A/AAAA/CNAME or relevant child NS delegation;
   either could keep a retired name publicly resolvable after exact target
   deletion. Inspect effective A/AAAA/CNAME answers from Cloudflare's
   authoritative servers for all 26 names and a concrete Cordium wildcard
   child, and block on a failed or non-authoritative response, an unexpected
   source, or incomplete inspection. Measure the previous maximum TTL only
   from validated authoritative responses.
   Preserve every out-of-scope record, including NS, until a separate scope
   and reviewed change resolve the conflict.

The private evidence JSON follows [the data model](../data-model.md). Its
`checked_names` must equal the derived 26-name set. The old 27-name evidence
template is invalid for this cutover and must be replaced with a fresh
preview. All acceptance fields require current observations; a successful
dry-run alone is insufficient.

## Deletion and readback

Before the first DELETE, re-read all 26 owners and the complete public-zone
wildcard/CNAME/NS inventory, block on relevant child delegation, and recheck
effective authoritative answers. Re-read all 26 owners' full record fields
again after that inspection and immediately before the first DELETE. Reject an
incomplete result, a wrong owner returned for an exact-name query, a new or
changed target A/AAAA/CNAME record, or a
current authoritative TTL above the saved maximum. Records at other owners
and non-address records at selected owners remain untouched; they are not
deletion targets. A live target set may be a subset of the baseline after a
partial run. Delete only current baseline IDs, then read each owner back and
require no target A/AAAA/CNAME records. A retry uses
the same reviewed code and evidence after investigating the failed write.

Preserve the public zone; all apex records including A and any existing CAA,
plus MX/TXT/NS/SOA; the four legacy names; intentionally public Mastodon if
published; and every unrelated name and record type. A conflicting
out-of-set wildcard, CNAME chain, or child-zone delegation blocks execution;
it never gives this helper permission to delete another owner or NS record.

## Post-cutover acceptance

Wait at least `previous_ttl_seconds` from the last deletion. For each of the
26 exact names and a concrete `*.cordium.stinkyboi.com` child, query the
effective authoritative nameservers after following any child delegation,
and a public recursive resolver for A, AAAA, and CNAME. No public answer of
those types may remain. Compare public apex A,
MX, TXT, and any existing CAA, plus representative unrelated names, with the
recorded pre-cutover baseline. Check that DNS-01 validation capability and
existing HTTPS certificates remain usable. Re-run the signed direct DNS
checker, ordinary tailnet OS lookups, HTTPS routes, and critical caller paths.

The fail-closed guarantee applies to the 26 retired subdomains. The apex has
an intentional public address and is outside that guarantee. During a
controlled resolver outage check, a retired subdomain must not receive a
public app address.

## Recovery and reversal

Diagnose with the read-only `scripts/tailnet-dns-check.py` against the
observed resolver IP, Argo health, Pods, Service status, and signed proxy
identity. Restore failed resolver declarations through reviewed
Terragrunt/Argo desired state, or re-sign only the fixed proxy when its key
rotates. Re-run direct and normal-client checks. Do not republish the retired
public addresses or relax Traefik restrictions as outage recovery. A policy
reversal requires a separate reviewed change and explicit owner decision.
