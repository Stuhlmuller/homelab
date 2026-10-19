# Implementation Plan: Retire Public App Subdomain DNS

**Branch**: `codex/tailnet-subdomain-retirement` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: The 26 approved non-apex app subdomains lose public A/AAAA/CNAME
records after private access passes. The public zone and apex remain.

## Summary

Narrow the existing guarded Cloudflare retirement helper from the fixed first
27 migration names to the 26 non-apex names. Keep private DNS for all 29
current names and HTTPS retirement readiness for the original 27 routes.
Capture a fresh exact Cloudflare baseline,
confirm normal tailnet DNS/HTTPS and caller paths, execute only from reviewed
`main`, then prove public absence after the old TTL while public apex, mail,
certificate validation, and unrelated names continue working.

## Technical Context

**Language/Version**: Bash and Python 3; JSON inventory/evidence; `jq`.

**Primary Dependencies**: Existing `aws` SSM credential lookup, `curl` to the
Cloudflare DNS API, `dig`, `kubectl`, Tailscale CLI, Traefik, and the deployed
CoreDNS/k8s_gateway resolver. No new runtime dependency.

**Storage**: One private local evidence JSON outside git; no new cluster state,
database, PVC, or secret.

**Testing**: Mocked Cloudflare/preflight tests in
`scripts/ci/tailscale-private-dns-test.py`, current private DNS source and
read-only checker tests, shell syntax and repository static checks, followed
by documented live read-only and post-cutover checks.

**Target Platform**: Trusted operator Mac with tailnet, read-only Kubernetes
access, and the existing SSM credential path; public Cloudflare zone for
`stinkyboi.com`; Talos Kubernetes homelab.

**Project Type**: Guarded operator CLI plus cutover documentation. No new DNS
service or ingress change.

**Performance Goals**: Read 26 exact deletion owners and the complete
paginated public-zone wildcard/CNAME/NS inventory at preview and again before
execution; read target owners back after deletion. Wait the measured old
maximum authoritative TTL. Existing private resolver TTL/cache limit remains
30 seconds.

**Constraints**: Preserve the public zone, all apex records including A,
any existing CAA and mail records, four legacy names, Mastodon and other
unrelated names. Keep 29 current private answers. Remove only exact A/AAAA/CNAME
records for 26 names; fail before a write on drift or missing evidence;
do not provide a public republishing fallback.

**Scale/Scope**: 26 fixed non-apex migration names, including a Cordium
wildcard owner; one existing Cloudflare zone and any delegated authoritative
child zone relevant to their public answers; no new controller or workload.

## Constitution Check

*GATE: Checked against ratified Homelab Constitution 1.0.0 before research and
again after Phase 1 design.*

| Principle | Result |
| --- | --- |
| I. Repository-Owned Desired State | Pass: change the repository helper and docs first; run the reviewed helper from merged `main`. No console or ad hoc cloud deletion. |
| II. Public Repository and Secret Safety | Pass: reuse the existing SSM secret reference; keep baseline IDs, evidence, private client outputs, and credentials outside git. |
| III. Validation Before Production Change | Pass conditional on the local tests, fresh live DNS/client/caller preflight, and post-TTL verification. No Kubernetes/Talos/IaC desired-state change is planned, so their apply gates are not triggered. |
| IV. Reviewable and Teachable Changes | Pass: reviewed PR for source/tests and current runbook/OpenWiki updates; document the exact write, verification, partial retry, recovery, and reversal. |
| V. Reproducible Bootstrap and Clear Ownership | Pass: keep the existing Terragrunt/Argo resolver and one-apply path; scripts own the helper, docs/runbook own procedure, OpenWiki owns cross-cutting context. |

No exception or unresolved technical clarification is needed for this scope.
Live acceptance evidence is a required execution gate, not assumed by this
plan. The 004 feature's all-27 public retirement wording is superseded only
for the public-record cutover; its original 27-name private approval remains
inside the current 29-name inventory.

## Design

1. **Separate sets:** Retain the fixed first 27 migration names and digest. Derive
   the retirement set as those ordered first 27 entries without exact apex
   `stinkyboi.com`, and validate its 26-name membership. Keep private DNS
   probes on all 29 current names and retirement HTTPS readiness on the first
   27 routes. The two staged Enterprise routes have a separate full route check.
   Accept a stopped migration backend only when its
   reviewed workload declaration and live Deployment both specify zero replicas;
   keep serving routes strict.
2. **Narrow the helper:** Use the 26-name set for Cloudflare deletion-target
   queries, dry-run output, baseline, old TTL measurement, current-vs-baseline checks,
   DELETE calls, and readback. Retain complete-page and exact-owner guards,
   idempotent partial retry, and no-publication behavior. Apex and legacy
   names must not be queried as deletion targets. Records at other owners and
   non-address types at selected owners are preserved. The API zone's
   nameservers must match live public delegation; a wrong owner returned for
   an exact-name query or a changed target baseline blocks execution. Re-read
   every target's full fields after the zone scan and immediately before the
   first DELETE to catch drift during inspection.
3. **Refresh evidence:** The new private template records 26 checked names and
   target records. Require `off_tailnet` to account for every retirement name
   with `migrated` or `accepted_loss`, plus existing owner DNS, normal-client,
   Fleet, Harbor, native API, Cordium, and public callback confirmations.
   A 27-name historical template must fail validation; capture a new baseline.
4. **Prove the boundary:** Before any DELETE, read the complete public-zone
   wildcard/CNAME/NS inventory. Block on any out-of-set covering wildcard
   A/AAAA/CNAME or relevant child NS delegation; no child-zone write or
   traversal is needed to establish a safe block. Inspect effective answers
   at the Cloudflare authoritative servers for all 26 targets and a concrete
   Cordium child, and block on a failed or non-authoritative response, an
   unexpected source, or incomplete inspection. Authoritative TTL measurement
   applies the same response validation before accepting a cache lifetime.
   Preserve out-of-scope wildcard, CNAME, and NS records pending separate
   reviewed scope. Tests cover this
   block, A/AAAA/CNAME at target names, apex A and MX/TXT survival, any
   existing CAA preservation, legacy and
   unrelated names, absent records, wrong-owner responses, changed baseline,
   incomplete page, missing evidence, and partial retry. After the old TTL,
   check authoritative and recursive public answers and normal tailnet access.
5. **Recover privately:** During a resolver fault, use the existing read-only
   checker and declared Argo/Terragrunt or fixed signer path. Keep retired
   public records absent. A policy reversal is a separate reviewed change.

## Project Structure

### Documentation (this feature)

```text
specs/005-retire-public-app-dns/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/cutover.md
└── tasks.md
```

### Source Code (repository root)

```text
scripts/config/tailscale-private-dns.json   # fixed first 27 plus two staged names
scripts/tailscale-private-dns.sh             # exact 26-name Cloudflare preview/delete
scripts/tailscale-private-dns-check.py       # narrowed evidence and TTL preflight
scripts/tailnet-dns-check.py                 # read-only current-name health check
scripts/ci/tailscale-private-dns-test.py     # mock cutover and no-write safety cases
docs/networking-tailnet-ingress.md           # current DNS model and cutover boundary
clusters/homelab/apps/traefik/CUTOVER.md     # operator procedure
clusters/homelab/platform/tailnet-dns/README.md  # resolver and retirement link
openwiki/runbooks/tailnet-ingress.md         # cross-cutting cutover context
openwiki/operations/validation-gates.md     # affected validation gate if wording changes
```

**Structure Decision**: Reuse the current scripts and documentation owners.
Do not change the deployed resolver, Traefik certificate, cert-manager issuer,
Tailscale policy, or Kubernetes manifests for this scope.

## Delivery Order

1. Merge the narrowed helper, tests, and affected current guides through the
   normal protected PR workflow. Confirm local validation at the reviewed SHA.
2. From clean `main`, gather fresh read-only live evidence for all 29 private
   answers, exact public target records, wildcard/CNAME/delegation conflicts, preserved
   public records, and critical caller paths. Preview the 26-name deletion
   into a new private evidence file; do not execute if a broader public
   answer would remain.
3. Complete/review all evidence, then execute the helper. A failed preflight
   leaves public records intact; a partial deletion is re-read and retried
   through the same reviewed path.
4. Wait the old TTL, prove 26-name public absence and preserved public zone
   behavior, then recheck private DNS, HTTPS, and callers. Record any unmet
   live acceptance separately; do not claim cutover complete from source tests.

## Post-Design Constitution Check

The Phase 1 data model and contract still use existing repository-owned
paths, keep private evidence out of git, require validation before the
Cloudflare write, and leave the Terragrunt/Argo bootstrap unchanged. All five
principles remain satisfied without an exception.
