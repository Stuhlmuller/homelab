# Unlocked-tailnet source validation

Base: 0f4f806262d9d2cf0ab1296334e4d907a2ce5f3f; isolated branch
fix/adguard-unlocked-tailnet. T048–T052 implemented; T053 still in progress.

- Checker suite: 26 passed after expected-red tests, via project nix develop.
- Cutover suite: 23 passed, including no apply on mode/identity drift and rollback
  with historical evidence lacking mode.
- Shared signer suite: 30 passed; source helper unchanged.
- python3 -I scripts/ci/adguard-recovery-test.py: 5 passed.
- python3 -I scripts/ci/openwiki-check.py: passed.
- git diff --check: passed.
- Independent adguard_research code review: no material findings; reviewed
  mode typing/agreement, exact identity/ownership, upstream fields, freshness,
  unchanged locked path, rollback and sanitized failures. No runtime claims.
- nix run --no-update-lock-file --no-write-lock-file .#validate: running;
  task-private log and session recorded in the coordinator ledger. Do not mark
  T053 complete until result is collected and any failure is resolved/reported.

No manifests, DNS policy, credentials, shared signing or cutover implementation
changed. No Mac DNS/admin/recovery or normal-client acceptance is claimed.
