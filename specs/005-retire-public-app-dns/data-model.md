# Data Model: Public App Subdomain Retirement

## Approved private name snapshot

`scripts/config/tailscale-private-dns.json` contains 29 `hostnames`: the fixed
first 27 migration names, including `stinkyboi.com`, followed by two staged
OpenClaw Enterprise names. Four `retired_hostnames` are separate. The live
private approval source remains the reviewed
`traefik-private` Service annotation paired with HTTPS routes. The resolver
answers all 29 approved names, including the apex.

Validation: names are unique, within the declared domain, and the first 27
retain their fixed migration digest. The four legacy names never enter the
approved set. Later private names require the route, annotation, and resolver
inventory contract but do not enter this one-time public retirement set.

## Public retirement set

The retirement set is the first 27 `hostnames` minus the exact apex
`stinkyboi.com`: 26 names. It includes the literal wildcard owner
`*.cordium.stinkyboi.com`; post-cutover checks also query a concrete child.
Only exact Cloudflare A, AAAA, and CNAME records at those owner names may be
deleted. The public apex, two staged Enterprise names, four legacy names,
Mastodon, unrelated names, and all other record types are outside the set.

Validation: derive the set from the fixed snapshot on each run; require 26
unique non-apex names. The shell helper, preflight, evidence, and tests must
use the same derived set. No broad suffix or zone match is allowed.

## Public record baseline

For each of the 26 owners, the helper reads the complete Cloudflare record
list and retains target records as `{id, name, type, content, proxied, ttl}`.
The complete baseline can be empty if retirement was already completed.
Record IDs and all fields are compared before a write. An absent individual
record is a no-op; a changed or newly added record blocks execution. A
partially deleted baseline remains resumable with the same reviewed evidence.

The largest old authoritative A/AAAA/CNAME TTL across the 26 owners is recorded
in seconds. It may be zero only when the target baseline is empty. The helper
re-measures it before execution and blocks if it exceeds the saved value.

## Cutover evidence

The private JSON file outside the public repository retains the helper's
existing fields, with `checked_names` and `baseline_records` narrowed to the
26-name retirement set:

| Field | Meaning and validation |
| --- | --- |
| `reviewed_main_sha` | Exact merged `main` revision used for execution |
| `resolver_ip` | Observed signed resolver tailnet IPv4 |
| `owner_tailnet_dns_confirmed` | Owner's restricted DNS setting confirmed |
| `normal_client_dns_confirmed` | Ordinary OS lookups for all 29 current names confirmed |
| `critical_paths_confirmed` | All existing Fleet, Harbor node pull, native API, Cordium reconnect, and public callback checks confirmed |
| `off_tailnet` | Exactly the 26 retirement names, each with an explicit `migrated` or `accepted_loss` decision for callers bypassing ordinary tailnet DNS |
| `previous_ttl_seconds` | Largest old authoritative TTL for the 26 target names |
| `checked_names` | Exact ordered 26-name retirement set queried in the preview |
| `baseline_records` | Exact target record tuples from the live Cloudflare preview |

All confirmation fields start false or empty in the private template. The
operator completes them only from current evidence. A baseline generated for
the prior 27-name contract is invalid and must be regenerated. Public apex and
unrelated-name before/after answers are retained in the operator's private
cutover record, outside the deletion input.

## State transitions

`previewed` → `accepted` → `executing` → `retired` → `verified`.

- **previewed**: complete live 26-name record baseline and old TTL captured;
  no mutation.
- **accepted**: reviewed main SHA, owner setting, all 29 private answers,
  original 27 migration HTTPS/access paths, and off-tailnet decisions recorded.
- **executing**: re-read target records and private readiness; delete exact
  baseline IDs only. A partial failure returns to `accepted` after the live
  subset and preflight are rechecked.
- **retired**: no A/AAAA/CNAME target records remain in Cloudflare readback.
- **verified**: after the old TTL, authoritative and recursive public answers
  are absent for all 26 names and a wildcard child; apex and unrelated public
  answers survive, and private clients still work.

A later resolver incident does not reverse `retired`; recovery restores the
private resolver. Reintroducing public app addresses requires a separate
reviewed policy change.
