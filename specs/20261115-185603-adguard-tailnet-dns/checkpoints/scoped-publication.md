# AdGuard scoped CI publication implementation

User steering: “Use the homelab cicd pipelines to deploy”. Existing deployment
and protected-delivery authorization persists. No Notion writes.

Current main advanced to b6063d41c993ec575c667134fa97818d5a5591b9 via PR1845
(Terragrunt scope repair) and PR1848 (Kuma image lane). Kuma protected publisher
run44030881358 succeeded. Original all-catalog run43777917412 failed on an
unrelated Python digest. Do not repeat that full-catalog failure without evidence.

T003 repair implemented in isolated /workspace/homelab-adguard-pipeline,
branch feat/adguard-image-pipeline, base b6063d41c993ec575c667134fa97818d5a5591b9.
Nine changed files; no commit or PR yet. Canonical feature worktree remains
/workspace/homelab-adguard at48e8b9e4 with its complete local app implementation.
Do not discard or overwrite its work when integrating newer main changes.

Added fixed image_scope=adguard to existing harbor-mirror.yml, modeled on merged
Kuma lane. Inventory includes exact catalog AdGuard v0.107.80 and Python
3.14.7-alpine3.23 init digests. Helper validates exact two-image bundle and full
catalog membership before credentials. Existing source, copy, alias, platform,
digest and complete authenticated pull checks unchanged. No credential or
permission expansion. Exact workflow/publisher policy hashes reviewed and updated.
Negative fixtures cover missing/extra images, mutated digests/repos and invalid
dispatch; docs and authored Harbor wiki describe supported scope and limits.
This is existing T003 pipeline repair, not a new feature or DNS design change.

Validation:108 publication tests PASS (adguard-pipeline-focused.log);147 Rego
unit tests PASS;61 workflow policy checks PASS;offline-static-checks.sh exit0;
OpenWiki and git diff --check PASS. Initial combined shell later returned127
because opa was absent AFTER publication tests passed. Supplied OPA1.16.2 through
temporary locked-nixpkgs shell per use-temporary-nix-packages; policy and wiki
verification independently exited0. No flake/lock change. No active test processes.
Logs are /workspace/adguard-progress/adguard-pipeline-{focused,policy,static}.log.
Full repository static gate remains for delivery/CI; do not claim it ran here.

Read pipeline paths: terragrunt-apply supports exact-main targeted app apply.
No existing CI workflow rotates operator OAuth. Harbor uses a separate production
TAILSCALE_AUTH_KEY; successful Kuma publication demonstrates that enrollment path.
Attempt to list GitHub secret NAMES returned403, no values requested or exposed;
do not infer administrator OAuth authority from enrollment key. Stored operator
OAuth401 remains unresolved, but does not block scoped image source/publication.

Next separate completed turn: scoped convergence for this T003 pipeline repair
per track-homelab-changes. If clean, signed prerequisite PR/protected delivery,
then dispatch existing harbor-mirror.yml with image_scope=adguard and exact new
main. Require success before T031 consumer review/merge. Reconcile original app
branch with new main carefully (overlap in terragrunt tests/script and offline
hash table), validate affected source and continue targeted CI deployment. No
request for routine permissions. Operator enrollment/signing and live DNS/client
acceptance remain required for actual goal completion. Goal active; new meaningful
progress resets prior no-progress wait count. No Notion, live AWS/Kubernetes
mutations or DNS cutover in this increment.
