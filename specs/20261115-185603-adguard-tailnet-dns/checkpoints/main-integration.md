# Main integration while prerequisite CI runs

Canonical /workspace/homelab-adguard branch feat/adguard-tailnet-dns now has
HEAD b6063d41c993ec575c667134fa97818d5a5591b9. Preserved the complete feature in
stash3418fbc9e4036721d440751936e2c4d852571f27 (do not drop yet) plus private
progress patch/status. Initial stash apply --index failed atomically on the
changed offline hash table; plain stash apply then merged without conflicts.
All86 non-overlapping feature files match the saved stash byte-for-byte.
Three overlapping files are offline-static-checks.sh, terragrunt-apply.sh and
terragrunt-apply-test.py. New main's fail-closed deleted-unit discovery and
fixture support are retained alongside AdGuard's targeted preflight/SSM path.
The current-main workflow hashes remain from main; only the feature's existing
validate.yml hash override remains in its diff. No new behavior beyond combining
these already-reviewed changes. Baseline DNS comparison revision48e8... remains
intentionally pinned; new main did not change the baseline tailnet DNS contract.

Integration validation session24394 COMPLETE exit0:35 targeted apply tests,
offline-static-checks.sh and git diff --check passed. Log:
/workspace/adguard-progress/adguard-main-integration.log. No dependency or lock
changes from integration. Separate scoped integration convergence is next.

Prerequisite PR1851 head05c1bd6... remains open; required repo check passed10m58s.
Terragrunt staticjob133913988228 is in Run Static Checks, all precedingstepspass.
Originalwatch49913 remains the only CI watcher. Optional Harbor audit baseline
failure is recorded separately; no protection changes. No deploy/DNS change.
Next separate turn: scoped integration convergence, continue PR1851 required
check completion/protected merge and exact-main adguard publisher dispatch.
Do not restart completed local tests without a new change or concern.
