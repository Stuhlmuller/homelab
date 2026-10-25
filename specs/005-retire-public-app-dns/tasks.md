# Tasks: Retire Public App Subdomain DNS

**Input**: Design documents in `specs/005-retire-public-app-dns/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [cutover contract](contracts/cutover.md), [quickstart.md](quickstart.md)

**Tests**: Include focused safety tests because this feature deletes live DNS records and the plan requires mocked Cloudflare and preflight coverage.

**Organization**: Work is grouped by user story. Source delivery and the guarded live cutover are separate tasks; no public record deletion is part of a source test.

## Phase 1: Setup (Existing Path)

**Purpose**: Confirm the fixed migration snapshot and the current guard before changing code.

- [X] T001 Inspect the 27 approved names, four legacy names, current Cloudflare helper, preflight, and mocked fixture in `scripts/config/tailscale-private-dns.json`, `scripts/tailscale-private-dns.sh`, `scripts/tailscale-private-dns-check.py`, and `scripts/ci/tailscale-private-dns-test.py`; keep the 27-name private inventory unchanged.

---

## Phase 2: Foundational (Shared Retirement Set)

**Purpose**: Establish one validated 26-name public deletion set while retaining all 29 current private answers.

- [X] T002 Add a failing test for the ordered 26 non-apex retirement names, fixed 27-name inventory digest, and excluded four legacy names in `scripts/ci/tailscale-private-dns-test.py`.
- [X] T003 Derive and validate the exact 26-name retirement set from the fixed inventory, excluding only `stinkyboi.com`, in `scripts/tailscale-private-dns-check.py`; preserve private DNS for every approved name and HTTPS checks for the original 27 migration routes.

**Checkpoint**: The preflight distinguishes public deletion targets from private resolver approvals.

---

## Phase 3: User Story 1 - Retire Public App Subdomain Answers (Priority: P1) 🎯 MVP

**Goal**: Delete only public A, AAAA, and CNAME records at the 26 approved non-apex owners after private access passes.

**Independent Test**: Mock a preview and execution, then confirm exactly the 26 owner names are queried and only their address records are removed; after live cutover, public authoritative and recursive answers are absent for those names and a concrete Cordium wildcard child.

- [X] T004 [US1] Add a failing 26-name dry-run test that excludes the apex from `checked_names`, `baseline_records`, Cloudflare target queries, and maximum-TTL calculation in `scripts/ci/tailscale-private-dns-test.py`.
- [X] T005 [US1] Use the validated 26-name set for Cloudflare queries, preview, baseline, TTL, DELETE, readback, and completion output in `scripts/tailscale-private-dns.sh`; keep direct private DNS for every approved name and HTTPS readiness on the original 27 migration routes.
- [X] T006 [US1] Add mocked execution cases for A/AAAA/CNAME removal, absent individual records, empty baseline, and the Cordium wildcard owner in `scripts/ci/tailscale-private-dns-test.py`.

**Checkpoint**: The guarded helper can retire the 26 exact owner names without selecting the apex.

---

## Phase 4: User Story 2 - Keep Intentional Public DNS Working (Priority: P2)

**Goal**: Preserve public apex, mail and validation records, other record types, and unrelated public names while private apex resolution remains healthy.

**Independent Test**: Mock a cutover with apex A/MX/TXT/CAA, NS/SOA, legacy, Mastodon, and other unrelated records; confirm none change, the current 29-name private checker still covers the apex, and read-only public DNS-01 readiness passes before and after live cutover.

- [X] T007 [US2] Extend Cloudflare fixtures and assertions so apex A/MX/TXT/CAA, NS/SOA, four legacy names, Mastodon and other unrelated owners, plus non-address types at target owners survive execution in `scripts/ci/tailscale-private-dns-test.py`.
- [X] T008 [P] [US2] Explain the preserved public zone, private apex, DNS-01 validation, and unrelated-name behavior; replace stale 27-name public-retirement wording with the 26-name boundary and keep legacy endpoints distinct in `docs/networking-tailnet-ingress.md`, `clusters/homelab/platform/tailnet-dns/README.md`, `docs/secrets-aws-ssm.md`, and `docs/octelium.md`.
- [X] T009 [US2] Verify resolver approval and apex coverage with `scripts/ci/tailnet-dns-check-test.py` and `scripts/ci/tailnet-dns-test.py`; the initial 27-name approval later expanded to 29 names.

**Checkpoint**: Public preservation and private apex behavior are explicit and testable independently of live deletion.

---

## Phase 5: User Story 3 - Complete a Guarded and Recoverable Cutover (Priority: P3)

**Goal**: Block deletion on missing evidence or drift, support safe partial retry, and document private-only recovery.

**Independent Test**: Reject a stale 27-name evidence file, missing caller decisions, changed or incomplete records, excess TTL, or a public wildcard/CNAME/child-delegation conflict before any DELETE; allow an unchanged partial subset to resume.

- [X] T010 [US3] Add failing evidence and no-write tests for exact 26-name
  `checked_names` and `off_tailnet`, old 27-name evidence rejection, missing
  confirmations, a wrong-owner response for a selected exact-name query,
  changed baseline including same-ID full-field drift during inspection,
  incomplete Cloudflare pages, wrong Cloudflare-zone nameservers,
  failed/non-authoritative TTL replies, excess TTL, deliberate zero-replica
  route exceptions, and safe partial retry in
  `scripts/ci/tailscale-private-dns-test.py`.
- [X] T011 [US3] Require exact 26-name evidence membership and record-owner/type validation while keeping all 29 current private-client DNS checks and the original 27 migration HTTPS checks, with serving routes strict and deliberately stopped backends accepted only on matching reviewed/live zero replicas, in `scripts/tailscale-private-dns-check.py`.
- [X] T012 [US3] Generate a fresh private evidence template with all 26 empty `off_tailnet` decisions and no apex target records in `scripts/tailscale-private-dns.sh`; reject historical 27-name templates rather than adapting them.
- [X] T013 [US3] Inspect the complete paginated public wildcard/CNAME/NS
  inventory, block on relevant child NS delegation or out-of-set covering
  wildcard A/AAAA/CNAME, and check effective Cloudflare authoritative answers
  for all 26 names plus a concrete Cordium child before any DELETE; re-read
  every target's full fields immediately before the first DELETE; fail closed
  on an unexpected source or incomplete inspection, preserve out-of-scope
  records, and add no-write wildcard/CNAME/delegated-NS and same-ID drift
  fixtures in `scripts/tailscale-private-dns.sh`,
  `scripts/tailscale-private-dns-check.py`, and
  `scripts/ci/tailscale-private-dns-test.py`.
- [X] T014 [P] [US3] Update exact 26-name preview, reviewed-SHA execution,
  caller evidence, previous-TTL verification, partial retry, and
  private-resolver recovery in `clusters/homelab/apps/traefik/CUTOVER.md` and
  `specs/005-retire-public-app-dns/quickstart.md`; add
  superseded-public-cutover notices and 005 links to 004's `spec.md`, `plan.md`,
  `research.md`, `tasks.md`, `data-model.md`, `quickstart.md`,
  `contracts/cutover.md`, and `contracts/dns-publication.md`, narrowing stale
  fail-closed text to the 26 retired non-apex names while retaining the
  historical 27-name private-resolver contract.
- [X] T015 [P] [US3] Replace stale 27-name public-retirement wording with the
  26-name boundary, add the 005 cutover link, and update source-linked cutover
  and secret context through the repository OpenWiki workflow in
  `openwiki/runbooks/tailnet-ingress.md`,
  `openwiki/architecture/gitops-flow.md`,
  `openwiki/architecture/secrets-and-identity.md`, and, if its gate text changes,
  `openwiki/operations/validation-gates.md`.

**Checkpoint**: A reviewed 26-name baseline and complete private/caller evidence are required before any Cloudflare write.

---

## Phase 6: Polish, Delivery, and Live Acceptance

**Purpose**: Validate and merge the reviewed code, then execute and verify the guarded cutover from `main`.

- [X] T016 Run `bash -n scripts/tailscale-private-dns.sh`, `python3 -I scripts/ci/tailscale-private-dns-test.py`, `python3 -I scripts/ci/tailnet-dns-check-test.py`, `python3 -I scripts/ci/tailnet-dns-test.py --initial-migration`, and `nix develop --command bash scripts/ci/static-checks.sh --offline-verified`; record any unavailable gate in `specs/005-retire-public-app-dns/tasks.md` or the PR.

**T016 validation (2026-10-18):** Bash syntax, 23 focused Cloudflare/preflight
tests, 9 direct DNS checker tests, the Nix private DNS declaration test,
ShellCheck, secret scan, OpenWiki check, and `git diff --check` passed. The
required
`nix develop --command bash scripts/ci/static-checks.sh --offline-verified`
was attempted but stopped at `nix-cache-signature-test.py`:
the `homelab-manifest-policy` Nix store output had no available substituter.
The affected DNS checks above passed independently.

- [X] T017 Review the changed helper, preflight, tests, runbooks, and OpenWiki pages, then merge their protected PR to `main` before any live DELETE; include `scripts/tailscale-private-dns.sh`, `scripts/tailscale-private-dns-check.py`, `scripts/ci/tailscale-private-dns-test.py`, and `clusters/homelab/apps/traefik/CUTOVER.md` in the review.

**T017 delivery (2026-10-19):** PR #1410 merged through the protected path at
`2f94bec3f4d42b4759bfe5cab566633eaa7cb6d3`; no public DNS records were
deleted. Revalidate current `main` before the live cutover because later changes
affect the private-name inventory and readiness checks.
- [ ] T026 Before T018's public-callback signoff, merge the guarded
  repository-owned retirement of unused Codex Review Helper hook `589400612`,
  run its exact-ID deletion from clean reviewed `main`, then verify the ID and
  callback path are absent while fresh Github Emergency Bot and Policy Bot
  deliveries still succeed; leave the inactive n8n workflow unpublished.
- [ ] T018 From clean reviewed `main`, capture read-only Argo, signed resolver,
  all 29 ordinary tailnet DNS answers, the original 27 migration HTTPS routes and declared/live
  zero-replica suspensions, Fleet, Harbor node pulls, native API, Cordium
  reconnect, public callbacks, apex, and unrelated-name observations outside
  git; before deletion also verify Cloudflare authoritative delegation, Ready
  status of the `cert-manager-cloudflare-api-token` ExternalSecret and
  `letsencrypt-cloudflare` ClusterIssuer, unchanged DNS-01 solver/secret
  references in `clusters/homelab/apps/cert-manager/externalsecret.yaml` and
  `clusters/homelab/apps/cert-manager/issuer.yaml`, and Ready Traefik and Istio
  Certificates from `clusters/homelab/apps/traefik/certificate.yaml` and
  `clusters/homelab/apps/istio/certificate.yaml` using
  `specs/005-retire-public-app-dns/quickstart.md` and
  `clusters/homelab/apps/traefik/CUTOVER.md`.
- [ ] T019 Run the reviewed dry-run from `scripts/tailscale-private-dns.sh` into `~/.local/state/homelab/app-subdomain-retirement.json`; review all 26 exact owner IDs/types, preserved public records, broader wildcard/CNAME/child-delegation conflicts, effective authoritative answers, and old maximum TTL before editing confirmation fields.

**T019 status:** An earlier read-only preview is stale after `main` advanced and
AWS SSO expired. Capture a fresh preview from current reviewed `main` before
completing evidence or deleting records.
- [ ] T020 Record current `migrated` or `accepted_loss` decisions for every one of the 26 names and confirm the owner DNS setting, all normal-client and critical-path checks, and exact baseline in `~/.local/state/homelab/app-subdomain-retirement.json`; stop if any evidence or caller decision is missing.
- [ ] T021 Execute `scripts/tailscale-private-dns.sh --retire-private --execute` from clean reviewed `main` with its exact `--expected-sha` and `~/.local/state/homelab/app-subdomain-retirement.json`; if a partial run occurs, investigate and retry only through the same guard after rechecking live state.
- [ ] T022 After the saved previous TTL from the last deletion, follow any
  child delegation and verify no effective authoritative or recursive public
  A/AAAA/CNAME answer for all 26 names and
  `dns-preflight.cordium.stinkyboi.com`; compare apex A/MX/TXT/CAA, NS/SOA,
  and unrelated public names with the private pre-cutover record, then repeat
  Cloudflare authoritative delegation, Ready
  `cert-manager-cloudflare-api-token` ExternalSecret, Ready
  `letsencrypt-cloudflare` ClusterIssuer, unchanged DNS-01 solver/secret
  references, and Ready Traefik and Istio Certificate checks using
  `specs/005-retire-public-app-dns/quickstart.md`,
  `clusters/homelab/apps/cert-manager/externalsecret.yaml`,
  `clusters/homelab/apps/cert-manager/issuer.yaml`,
  `clusters/homelab/apps/traefik/certificate.yaml`, and
  `clusters/homelab/apps/istio/certificate.yaml`.
- [ ] T023 Recheck ordinary tailnet DNS for all 29 names, the original 27 migration HTTPS/access restrictions, critical callers, and isolated-client fail-closed behavior for sampled retired names; record results and restore private DNS only through the declared path if needed, following `clusters/homelab/apps/traefik/CUTOVER.md` and `specs/005-retire-public-app-dns/contracts/cutover.md`.

**Checkpoint**: The source is merged, the public 26-name retirement is observed after cache expiry, preserved public DNS still works, and private app access passes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** starts immediately.
- **Foundational (Phase 2)** follows setup; T003 follows the failing test T002.
- **US1 (Phase 3)** follows foundational; T005 follows T004, then T006 checks execution behavior.
- **US2 (Phase 4)** uses the US1 deletion path but its preservation fixtures and documentation can be prepared in parallel.
- **US3 (Phase 5)** uses the same 26-name set and deletion path; T011–T013 follow failing safety tests T010. Documentation can proceed in parallel.
- **Polish and live acceptance (Phase 6)** follows all source changes; T017 follows local validation, T026 precedes T018's callback signoff, T018–T020 are read-only gates, T021 is the sole public DNS write, and T022–T023 follow its last deletion and previous TTL.

### User Story Dependencies

- **US1 (P1)**: Depends on the shared 26-name set; delivers the smallest working cutover helper.
- **US2 (P2)**: Tests preservation on the US1 helper; no new runtime service or DNS publication path.
- **US3 (P3)**: Adds evidence and conflict guards to the US1 helper before live use; live deletion depends on all three stories, a merged PR, and current accepted evidence.

### Parallel Opportunities

- T008 can proceed while T007 adds preservation fixtures because the files differ.
- T014 and T015 can proceed alongside T010–T013 because the documentation files differ from the helper and tests.
- T018's independent read-only checks can be delegated, but the private evidence review in T020 remains one operator gate.

### Parallel Example: User Story 2

```text
Task A: T007 preservation fixtures in scripts/ci/tailscale-private-dns-test.py
Task B: T008 public/private DNS explanation in docs/networking-tailnet-ingress.md, clusters/homelab/platform/tailnet-dns/README.md, docs/secrets-aws-ssm.md, and docs/octelium.md
```

### Parallel Example: User Story 3

```text
Task A: T010 safety fixtures in scripts/ci/tailscale-private-dns-test.py
Task B: T014 cutover instructions in clusters/homelab/apps/traefik/CUTOVER.md and specs/004-tailnet-service-dns/ plus specs/005-retire-public-app-dns/quickstart.md
Task C: T015 OpenWiki context in openwiki/runbooks/tailnet-ingress.md and openwiki/architecture/
```

## Implementation Strategy

1. **MVP**: Finish Phases 1–3 so exact 26-name targeting and no-apex deletion are proved locally; do not execute a live deletion from an unmerged branch.
2. **Safety**: Finish US2 and US3 preservation, evidence, and pre-delete conflict checks; validate and merge the reviewed source.
3. **Cutover**: Capture a fresh private baseline and current caller evidence on clean `main`, execute only through the helper, wait the old TTL, and verify public absence plus private and preserved-public behavior.

## Phase 7: Convergence

- [X] T024 Correct the unqualified public-resolution claim for `nofx.stinkyboi.com` in `clusters/homelab/apps/nofx/README.md` and, through the native OpenWiki update workflow, `openwiki/apps/nofx.md`; distinguish the current private DNS path from public-record retirement status without claiming live deletion before T021–T023, per FR-002 and FR-010 (partial).

## Phase 8: Convergence

- [ ] T025 After T022–T023 verify the live cutover, update `clusters/homelab/apps/nofx/README.md` and `openwiki/apps/nofx.md` through a reviewed follow-up PR and the native OpenWiki workflow to state the verified public-record status with dated evidence; if retirement is deferred or incomplete, retain accurate pending/partial wording, per FR-010 (partial).
