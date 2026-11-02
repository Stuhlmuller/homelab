# Tasks: Production-only Harbor signing recovery

Local preparation versus gated execution; completed DNS migration tasks in004/005
are preserved and not reopened. Feature pointer now selects006. No live success
is inferred from tests. Dependencies are sequential; no parallel execution grants.

## Setup and foundation

- [X] T001 Reconcile .specify/feature.json to scoped006 and preserve completed migration plan/tasks; save prior pointer under /private/tmp/harbor-signer-speckit-feature-before.json.
- [X] T002 Verify pinned installed CLI sign/stdin/add-before-output semantics in specs/006-harbor-production-key-recovery/research.md.
- [X] T003 Record the bounded generation/expiry/authority risk and separate gates in specs/006-harbor-production-key-recovery/spec.md and plan.md.

## US1: Prepare only the production signer

Independent acceptance:mocked exact invocation can append only one apply record;
wrong identity/pins/provider/actor/signer/version/source cause zero signing calls.

- [X] T004 [US1] Implement strict production-only pins/read-only preview and secret-safe capture in scripts/harbor-tailscale-production-sign.py.
- [X] T005 [US1] Add inert scope,secret-safety,CLI-contract and private-file tests in scripts/ci/harbor-tailscale-production-sign-test.py.

## US2: Recover interrupted completion without another signing attempt

Independent acceptance:complete captured output reconciles exactly once; lost or
partial output,foreign trust/cache changes and unsafe files fail closed.

- [X] T006 [US2] Implement intent-before-call,protected capture,exclusive lock,readback/cache-append journal and recover-only state machine in scripts/harbor-tailscale-production-sign.py.
- [X] T007 [US2] Test timeout,nonzero,interruption,partial output,delayed trust and interruption after cache commit in scripts/ci/harbor-tailscale-production-sign-test.py.
- [X] T008 [US2] Register ONLY mocked tests in scripts/ci/offline-checks.sh.
- [X] T009 [US2] Finish focused safety/spec/standards review and lint receipts in specs/006-harbor-production-key-recovery/review.md; repair findings locally.

## US3: Preserve independent future approval gates — none authorized now

Independent acceptance:the local artifact and tasks clearly mark each live step
unchecked; no completed migration permissions are borrowed for a new authority.

- [ ] T010 [US3] Obtain explicit source-publication approval for the exact signer/test/spec patch; publish/review through protected source workflow. Include affected authored openwiki/runbooks/ci-cd.md notes through the native OpenWiki workflow for the new signer,private intent/capture and separate authority-approval contract. Existing1753 approval covered only its completed prefix correction.
- [ ] T011 [US3] After reviewed source reaches signed currentmain, run a separately authorized fresh preview from specs/006-harbor-production-key-recovery/quickstart.md; bind actual Mac,current provider record and artifact digest.
- [ ] T012 [US3] Obtain explicit one-production-key signing/new-persistent-authority approval for scripts/harbor-tailscale-production-sign.py and its exact invocation; do not install a secret.
- [ ] T013 [US3] Execute approved signing ONCE; retain private intent/output/cache receipts and public authority readback. Use recover-only after uncertainty,as documented in contracts/signer.md.
- [ ] T014 [US3] Separately approve only homelab-production/TAILSCALE_AUTH_KEY installation through scripts/harbor-tailscale-production.py after exact new authority/generation/expiry review; preserve plan/Cordium and old authorities.
- [ ] T015 [US3] Separately approve protected mirror dispatch and complete image/backup/restore acceptance before resuming1752 deployment; preserve existing docs/harbor-tailscale-production.md gates.

Optional authority retirement is a separate future request with exact authority
and affected-signature inventory,never an automatic task or cleanup here.

## Delivery strategy

T001–T009 are local preparation. T010 source publication/merge must precede
T011–T013. T012 approval must precede any real sign call. T014 secret approval
and T015 mirror/deployment approvals are independent. There is no migration
phase,broader identity publisher,new provider key or default live operation.

## Local preparation receipt

2026-10-29:22 mock-only tests passed,Ruff passed,bash syntax and git whitespace
checks passed. SpecKit setup_plan/setup_tasks/check_prerequisites resolved006.
Standards/spec source reviews found two doc issues and one recovery timing issue;
all addressed. No real sign command,key generation,provider mutation,cache/
receipt write outside inert fixtures,secret install,enrollment,retirement,source
publication,CI dispatch or runtime action occurred. T010–T015 remain unchecked.
