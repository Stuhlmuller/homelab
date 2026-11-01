# Implementation Plan: Production-only Harbor signing recovery

Feature:006-harbor-production-key-recovery. Actual Git branch remains
codex/harbor-tailscale-production. Local preparation only; source unpublished.

## Scope reconciliation

The saved .specify/feature.json pointed to completed005-retire-public-app-dns.
Move only the local active feature pointer to006; preserve all completed005
and004 DNS specs/plans/tasks. Do not reclassify the Mastodon blocker as an
unfinished DNS/Octelium migration or renew previous migration permissions.

## Technical context

Python3 standard library, existing production/helper guard imports, Terragrunt
read-only outputs and the already installed Mac CLI1.92.3 at commit
9a08e8f1c2021d5c85895e660cf01d8bb1bc9df0. No new dependencies or credentials.
Storage:existing0700 cache directory,0600 cache/lock,distinct production intent
JSON and captured stdout. Test:mock all external commands; real inert tempfiles
exercise permission/durability behavior. One production signing attempt only.

## Constitution check, before and after design

All five principles pass for local preparation: repository-owned code precedes
any live action; no secrets in source; mocked validation before production;
reviewable runbook/contracts; current bootstrap/helper ownership unchanged.
Publication, signing and rollout remain unchecked gates, not exceptions.

## Architecture and state machine

New scripts/harbor-tailscale-production-sign.py imports existing read-only
production/shared guards without modifying either helper. Pins only the current
existing apply key, generation2,expiry2027-01-25T02:58:13Z. Existing full three-
identity publisher is never invoked. The cached bundle is read opaquely; only a
new apply record can be appended. Existing records and old authorities remain.

preview -> no mutation. Approved execute -> exclusive lock -> recheck source,
provider and trust -> fsynced intent -> protected fsynced capture file -> ONE
stdin signing call -> validate captured output/trust -> verified intent ->
atomic cache append -> complete receipt. Never publish a secret.

Any existing intent/capture blocks execute. recover reads the same pinned key,
receipt and output; never invokes sign. Complete output and exact trust/cache
proof permit idempotent completion. Partial/missing output, absent/unexpected
trust, changed cache or mismatched provider/pins stops and retains evidence.
A remote grant can succeed before stdout exists: lost private output cannot
be reconstructed. Separate exact orphan assessment/retirement approval needed.

## Files and delivery order

- scripts/harbor-tailscale-production-sign.py: new bounded signer/recovery.
- scripts/ci/harbor-tailscale-production-sign-test.py: only inert fixtures.
- scripts/ci/offline-checks.sh: register the mock-only test; no live execution.
- specs/006-harbor-production-key-recovery/: spec,plan,research,data model,
  CLI contract,quickstart,tasks and safety gate evidence.
- .specify/feature.json: local active-feature reconciliation only.

Finish source/tests/local review first. Source publication and protected merge
need separate authorization. Then fresh read-only preview and concrete action-
time signing approval; then separate secret install and live mirror acceptance.
Fresh backup/restore proof and existing1752 runtime approval gates stay in force.
No authority retirement, new migration or automatic fallback is part of this plan.
