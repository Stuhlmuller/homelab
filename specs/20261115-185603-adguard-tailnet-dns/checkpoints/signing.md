# T014 fixed signing target

Added automation/svc/adguard-dns/homelab-adguard/tag:homelab-ingress to the
existing fixed target list, with mutually exclusive --adguard-only selection.
Existing local trusted Mac signer, authenticated API, current-main and identity
recheck guards remain authoritative. No webhook signing trust expanded.

Four new tests first failed before implementation. Full signer suite now passes
30 tests, covering exact identity, wrong owner/namespace/name/tag/offline/lock,
selection, exclusive CLI preview, changed main and replaced proxy before sign.
Evidence: /workspace/adguard-progress/adguard-sign-red.log and
adguard-sign-final.log. git diff --check passes. README documents exact CLI and
its scope. No actual signing executed; source unmerged, runtime not deployed.

T014 complete; T015 remains next after separate scoped signing convergence.
Publisher43777917412 still copying/verifying, watcher80837 retains ownership.
No Notion updates. No hooks configured.
