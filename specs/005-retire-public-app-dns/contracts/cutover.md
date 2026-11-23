# Public App DNS Scope and Verification

## Scope and interface

The supported preparation interface is read-only:

```sh
scripts/tailscale-private-dns.sh --retire-private --dry-run --baseline-out <PRIVATE_FILE>
python3 -I scripts/tailscale-private-dns-check.py --retire-private --check
```

The dry run reads Cloudflare and authoritative DNS and may save private local
evidence; it does not change public records. The route check verifies reviewed
private HTTPS paths. Neither proves the complete direct resolver/client contract.
The current retirement execution path cannot complete its required private-DNS
validation, so this document offers no write procedure or bypass.

The fixed public scope is 26 approved non-apex owners from the original inventory,
including the Cordium wildcard owner. Preserve the public zone, all apex records
including A/MX/TXT/CAA/NS/SOA, the four retained public endpoints, Mastodon,
Enterprise names and every unrelated owner/type. The helper has no record-publication
or restoration mode. Private DNS continues to serve the current approved names.

## Read-only preparation

Use reviewed current `main` and keep evidence outside the checkout. Confirm the
selected Cloudflare zone's nameservers match parent delegation. Read every exact
public owner with complete pagination and compare IDs, types, fields and maximum
authoritative TTL. Inspect public wildcard/CNAME/child-NS conflicts and effective
authoritative answers for all selected names and a concrete Cordium child.
Do not alter conflicting or out-of-scope records.

Match the observed DNS Service address to its online, Service-owned device and
perform the [direct resolver verification](../../../docs/networking-tailnet-ingress.md#direct-resolver-verification)
for all approved names over UDP/TCP. Confirm ordinary OS resolution, canonical
HTTPS, intentionally stopped-app declarations, Fleet check-in, Harbor pulls,
native API, Cordium and authenticated callbacks separately. Keep an explicit
`migrated` or `accepted_loss` decision for every affected off-tailnet caller.
A dry run, fixture, receipt or single representative query does not prove these
acceptance conditions and cannot substitute for executable write validation.

## Public absence and preservation checks

For already retired names, wait the recorded previous maximum TTL from the last
confirmed change. Query all 26 exact names and a concrete Cordium wildcard child
for A/AAAA/CNAME at effective authoritative nameservers and a public recursive
resolver. Require no address/CNAME answer; unexpected wildcard or CNAME responses
need investigation. Compare apex mail/address records, unrelated names, delegation,
DNS-01 readiness and existing certificates with the preserved baseline.

## Recovery and reversal

During a private resolver failure, inspect Argo health, Pods, Service ownership,
online device identity and bounded direct UDP/TCP answers. Restore private
resolution through declared Argo/Terragrunt state and repeat direct, normal-client
and HTTPS checks. Retired subdomains have no public application fallback. The
public apex retains its intentional address and is outside that guarantee.
Do not republish app records or relax route restrictions as an outage workaround.
A DNS policy reversal requires its own reviewed repository change.
