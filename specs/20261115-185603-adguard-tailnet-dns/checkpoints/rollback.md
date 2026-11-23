# T025–T026 rollback source

Prior separateT043 convergence confirmed provider-reference resolution and exact
administrator identity binding, no additional findings/writes. This transcribes
that result. US4 rollback depends on completedT017/T023; client work remains open.

Added rollback fixtures first, then a separate rollback engine/CLI mode. It
requires the protected original receipt, current main restoring pinned prior
policy, recorded activation matching its ancestor source and an exact DNS-only
saved plan. It rechecks main/source, live policy, receipt and plan digest with
shared300s/60s bounds. It never invokes AdGuard checks/snapshot, requires no
AdGuardserver/password arguments, and doesn't require peer/filter/UI/DNS health.
The captured activation must itself preserve original private/MagicDNS/search
policy. Unknown/unrelated live policy or missing recovery record fails closed.

Already-restored returns no-op without a plan; otherwise native saved-plan apply
retains provider/state locks/encryption. Nested rollback receipt preserves the
original cutover evidence. Uncertain writes are inspected, never blindly retried;
failed attempts need new plans after inspection. No storage/secret/peer mutation.
README now documents the exact rollback CLI and control-plane access requirement.

All21 cutover/rollback tests pass, including offline AdGuard methods that raise if
called, exact restoration, missing/wrong source records, private-DNS mutation,
last-moment live drift, already-restored and uncertain success no-repeat cases.
Initial fixture setup dispatched an overridden rollback plan during creation of
its synthetic cutover record; fixed setup, then confirmed missing rollback engine
as the red failure before implementation. Logs adguard-rollback-red.log and
adguard-rollback-final.log. Targeted2-file secret scan0findings in
adguard-rollback-secrets.log. git diff --check passes.

T025/T026 complete at source/fixture level. No live rollback, deployment
or DNS change. Next separate scoped rollback convergence, then clientT018/T019,
provider expectationsT020 and isolated recoveryT027/T028; full integration/delivery
still pending. Publisher43777917412 sole watcher80837 still copying/verifying.
No Notion writes; hooks empty.
