# Unlocked snapshot and cutover binding: T050–T051

Scoped implementation complete; stop before T052 documentation. Continued the
repository Spec Kit implementation skill with the existing passing analysis.
Prerequisite helper resolved this feature; all checklists remain complete
(requirements 16/16, deployment-quality 24/24, unlocked-tailnet 12/12).
Extensions still declare no hooks. No design or requirements changes.

## Tests first

Added mode-aware snapshot validation and collector-wiring tests in
`scripts/ci/adguard-check-test.py`. Extended direct acceptance fixtures to reject
mode/key drift while verifying DNS samples, filtering and admin checks still run.
Added normal-client regression coverage requiring fresh direct acceptance,
reviewed active DNS policy, actual adapter sample invocation and unchanged final
client/mode identity; wrong policy, client drift, mode drift and sample failure
remain rejected. Existing cache/system-resolver/client-metadata tests remain.

Added `scripts/ci/adguard-dns-cutover-test.py` coverage for valid unlocked peer
binding and no apply on fresh mode/signature/key/device/Pod/tag/address drift,
plus a historical receipt that cannot replace required fresh direct acceptance.
The rollback regression explicitly asserts its historical peer evidence lacks
lock_enabled and still restores policy with AdGuard unavailable.

Before integration, `nix develop --command python3 -I scripts/ci/adguard-check-test.py`
ran 26 tests with exactly the expected two failing tests: unlocked evidence was
rejected by the unconditional signed check, and snapshot still called the legacy
signer path. The cutover suite already passed all 23 tests, demonstrating existing
full-peer comparison handles the new drift fields without a production change.

## Implementation and green verification

`scripts/adguard-check.py` now calls `inspect_adguard_peer()` from snapshot and
requires explicit boolean lock_enabled/signed with the mode-appropriate value
and expected DNS identity. Current-main, source/deployed/config, Service reread,
full before/after snapshots and normal-client gates remain unchanged.

- `nix develop --command python3 -I scripts/ci/adguard-check-test.py`: 26 pass.
- `python3 -I scripts/ci/adguard-dns-cutover-test.py`: 23 pass after integration.
- `git diff --check`: pass.
- No changes to `scripts/adguard-dns-cutover.py` or the shared signer. Their
  existing timing, live-policy, source, exact-plan and independent rollback
  guards remain intact. Unchanged signer tests were not repeated this turn.

Only T050 and T051 marked complete in this turn. T052 documentation and later
validation/delivery/live acceptance remain outstanding. No commit, PR, credentials
inspection or live mutation; synthetic fixtures are not Mac functional evidence.
Coordinator owns the next distinct stage. No background runner remains.
