# T015 read-only direct acceptance

The preceding separate signing convergence inspected T014 against the plan,
existing trust boundary and five constitution principles. No corrective findings,
no file changes. This transcribes that result in the following implementation.

Implemented scripts/adguard-check.py with clean signed current-main verification,
exact desired resource projection (Deployment, Services, ExternalSecret and init
ConfigMap), healthy synced app revision, current one-replica rollout, ready ESO,
observed Service UID/IP and existing signer/proxy identity validation. Re-reads
Service around proxy inspection, then rechecks the full snapshot after DNS tests.
No Secret values are fetched. Admin credential is supplied in an owned regular
mode0600 file, no symlinks; HTTPS validates certificates, disables environment
proxies and rejects redirects before credentials can be forwarded elsewhere.

Authenticated active-filter status requires the pinned runtime, protection,
expected daily-updated enabled nonempty list and actual matched rule/list ID for
both A/AAAA. Ten blocked/permitted A samples per transport plus blocked/permitted
AAAA, NXDOMAIN and the declared private-name inventory use one attempt and a
hard3-second subprocess timeout per query. Entire direct check is bounded300s.
Internal receipt binds source/deployed/config digest/revision, Service, peer and
filter result; explicitly mode=direct, client_acceptance=false,
admin_acceptance=false. Separate client/admin contracts remain T018/019/024.

Fixtures first failed on absent checker. Seven boundary tests now pass including
source/address/signature drift, filter membership, deadline/no retries, private
credential files, redirect rejection, final snapshot drift and no false client
proof. Added pinned-image API contract fixture: real AdGuard returns null for
empty whitelist_filters; accept only explicit null or empty list, preserving
missing-field rejection. All5 runtime tests pass. Checkov targeted secret scan
4 files passes0 findings; git diff --check passes. Logs adguard-check-red.log and
adguard-acceptance-final.log under /workspace/adguard-progress. Source API evidence:
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.80/openapi/openapi.yaml
(the relevant filter/status/check_host schemas inspected, local upstream/openapi.yaml).

Registered checker tests in offline checks and documented exact CLI in app README.
No live acceptance attempted: source dirty/unmerged, app not deployed. No live
signing or DNS changes. Publisher43777917412 still Copy And Verify Fixed Public
Digests, watcher80837 sole owner. T003 pending. T008–T015 source now complete;
next separate scoped convergence on T015, then dependency-ordered next story.
No Notion updates. Hooks empty.
